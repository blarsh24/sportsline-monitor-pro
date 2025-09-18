#!/usr/bin/env python3
"""
SportsLine Monitor - Enhanced Version
Notifies Discord when Bruce Marshall's page changes
"""

import requests
from bs4 import BeautifulSoup
import hashlib
import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

class SportsLineMonitor:
    def __init__(self):
        # Credentials & webhook
        self.email = os.environ.get('SPORTSLINE_EMAIL')
        self.password = os.environ.get('SPORTSLINE_PASSWORD')
        self.webhook = os.environ.get('DISCORD_WEBHOOK_URL')

        # URLs
        self.expert_url = "https://www.sportsline.com/experts/51297150/bruce-marshall/"
        self.login_url = "https://www.sportsline.com/login"

        # Requests session
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
        })

        # State file (consistent with workflow)
        self.state_file = 'picks_seen.json'
        self.load_state()

    def log(self, msg: str):
        """Print with timestamp for better debugging"""
        now = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        print(f"{now} {msg}")

    def load_state(self):
        """Load last known page hash"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.last_hash = data.get('last_hash', '')
                    self.last_check = data.get('last_check', '')
            else:
                self.last_hash = ''
                self.last_check = ''
        except Exception as e:
            self.log(f"⚠️ Could not load state: {e}")
            self.last_hash = ''
            self.last_check = ''

    def save_state(self, new_hash):
        """Save current page hash"""
        try:
            data = {
                'last_hash': new_hash,
                'last_check': datetime.now().isoformat()
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            self.log(f"⚠️ Could not save state: {e}")

    def login(self):
        """Login to SportsLine"""
        try:
            self.log("Logging in to SportsLine...")
            response = self.session.get(self.login_url)
            soup = BeautifulSoup(response.content, 'html.parser')

            login_data = {
                'email': self.email,
                'password': self.password
            }

            # Collect hidden fields
            form = soup.find('form')
            if form:
                for hidden_input in form.find_all('input', type='hidden'):
                    name = hidden_input.get('name')
                    value = hidden_input.get('value', '')
                    if name:
                        login_data[name] = value

            resp = self.session.post(self.login_url, data=login_data)

            if resp.status_code == 200:
                self.log("✅ Login request sent")
                return True
            else:
                self.log(f"❌ Login failed with status {resp.status_code}")
                return False

        except Exception as e:
            self.log(f"❌ Login error: {e}")
            return False

    def get_page_content(self):
        """Fetch Bruce Marshall's page content"""
        try:
            self.log("Fetching Bruce Marshall's page...")
            response = self.session.get(self.expert_url)

            if response.status_code != 200:
                self.log(f"❌ Error: Got status {response.status_code}")
                return None

            soup = BeautifulSoup(response.content, 'html.parser')

            # Strip unnecessary elements
            for element in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'noscript']):
                element.decompose()

            content = soup.get_text(separator=" ")
            content = ' '.join(content.split())

            self.log(f"Got {len(content)} characters of content")
            return content

        except Exception as e:
            self.log(f"❌ Error fetching page: {e}")
            return None

    def calculate_hash(self, content):
        """Hash content based on likely picks section"""
        if not content:
            return None

        picks_section = ""
        keywords = ['pick', 'play', 'bet', 'unit', 'spread', 'total', 'money line']

        for keyword in keywords:
            if keyword in content.lower():
                idx = content.lower().index(keyword)
                start = max(0, idx - 1000)
                end = min(len(content), idx + 5000)
                picks_section += content[start:end] + "\n"

        if not picks_section:
            picks_section = content

        return hashlib.md5(picks_section.encode()).hexdigest()

    def send_discord_alert(self, retries=3, delay=3):
        """Send alert to Discord with retries"""
        est_time = datetime.now(ZoneInfo("America/New_York")).strftime('%I:%M %p EST')

        embed = {
            "title": "🚨 New Bruce Marshall Pick Available!",
            "description": "Bruce Marshall has posted a new pick on SportsLine",
            "color": 0xFF0000,
            "fields": [
                {"name": "🔗 View Pick", "value": f"[**Click here**]({self.expert_url})", "inline": False},
                {"name": "⏰ Alert Time", "value": est_time, "inline": True}
            ],
            "footer": {
                "text": "SportsLine Premium Monitor",
                "icon_url": "https://www.sportsline.com/favicon.ico"
            }
        }

        payload = {
            "username": "SportsLine Alert",
            "content": "@everyone New pick from Bruce Marshall!",
            "embeds": [embed]
        }

        for attempt in range(1, retries + 1):
            try:
                resp = requests.post(self.webhook, json=payload)
                resp.raise_for_status()
                self.log("✅ Alert sent to Discord")
                return True
            except Exception as e:
                self.log(f"⚠️ Discord send failed (attempt {attempt}): {e}")
                if attempt < retries:
                    time.sleep(delay)

        return False

    def run(self):
        """Main monitoring loop"""
        self.log("=" * 50)
        self.log("SportsLine Monitor started")
        self.log("=" * 50)

        if not self.email or not self.password:
            self.log("❌ Missing SportsLine credentials")
            return
        if not self.webhook:
            self.log("❌ Missing Discord webhook")
            return

        if not self.login():
            self.log("❌ Login failed, aborting")
            return

        content = self.get_page_content()
        if not content:
            self.log("❌ Could not fetch page content")
            return

        current_hash = self.calculate_hash(content)
        if not current_hash:
            self.log("❌ Could not generate hash")
            return

        self.log(f"Current hash: {current_hash[:8]}...")
        if self.last_hash:
            self.log(f"Previous hash: {self.last_hash[:8]}...")
        else:
            self.log("No previous hash")

        if self.last_hash and current_hash != self.last_hash:
            self.log("🎯 PAGE CHANGED - New pick detected!")
            if self.send_discord_alert():
                self.save_state(current_hash)
                self.log("✅ State updated")
            else:
                self.log("⚠️ Alert failed, will retry next run")
        elif not self.last_hash:
            self.log("📝 First run - saving initial state")
            self.save_state(current_hash)
        else:
            self.log("✅ No changes detected")

        self.log("=" * 50)
        self.log("Check complete")

if __name__ == "__main__":
    monitor = SportsLineMonitor()
    monitor.run()
