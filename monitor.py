#!/usr/bin/env python3
"""
SportsLine Monitor - SIMPLE ALERT VERSION
Just notifies when Bruce Marshall's page changes
"""

import requests
from bs4 import BeautifulSoup
import hashlib
import json
import os
from datetime import datetime

class SimpleMonitor:
    def __init__(self):
        # Credentials
        self.email = os.environ.get('SPORTSLINE_EMAIL')
        self.password = os.environ.get('SPORTSLINE_PASSWORD')
        self.webhook = os.environ.get('DISCORD_WEBHOOK_URL')
        
        # URLs
        self.expert_url = "https://www.sportsline.com/experts/51297150/bruce-marshall/"
        self.login_url = "https://www.sportsline.com/login"
        
        # Session
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
        })
        
        # State file to track page changes
        self.state_file = 'page_state.json'
        self.load_state()
    
    def load_state(self):
        """Load the last known page hash"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.last_hash = data.get('last_hash', '')
                    self.last_check = data.get('last_check', '')
            else:
                self.last_hash = ''
                self.last_check = ''
        except:
            self.last_hash = ''
            self.last_check = ''
    
    def save_state(self, new_hash):
        """Save the current page hash"""
        try:
            data = {
                'last_hash': new_hash,
                'last_check': datetime.now().isoformat()
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Could not save state: {e}")
    
    def login(self):
        """Simple login to SportsLine"""
        try:
            print("Logging in to SportsLine...")
            
            # Get login page
            response = self.session.get(self.login_url)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Setup login data
            login_data = {
                'email': self.email,
                'password': self.password
            }
            
            # Add any hidden form fields
            form = soup.find('form')
            if form:
                for hidden_input in form.find_all('input', type='hidden'):
                    name = hidden_input.get('name')
                    value = hidden_input.get('value', '')
                    if name:
                        login_data[name] = value
            
            # Submit login
            self.session.post(self.login_url, data=login_data)
            print("Login completed")
            return True
            
        except Exception as e:
            print(f"Login error: {e}")
            return False
    
    def get_page_content(self):
        """Get Bruce Marshall's page content"""
        try:
            print("Fetching Bruce Marshall's page...")
            response = self.session.get(self.expert_url)
            
            if response.status_code != 200:
                print(f"Error: Got status code {response.status_code}")
                return None
            
            # Parse the page
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Get the main content area (picks are usually in main content)
            # Remove headers, footers, ads, etc.
            for element in soup.find_all(['script', 'style', 'nav', 'header', 'footer']):
                element.decompose()
            
            # Get text content
            content = soup.get_text()
            
            # Clean it up
            content = ' '.join(content.split())
            
            print(f"Got {len(content)} characters of content")
            return content
            
        except Exception as e:
            print(f"Error fetching page: {e}")
            return None
    
    def calculate_hash(self, content):
        """Calculate a hash of the content to detect changes"""
        if not content:
            return None
        
        # Focus on the part that likely contains picks
        # Look for keywords that indicate picks section
        picks_section = content
        
        # Try to find the picks area
        keywords = ['pick', 'play', 'bet', 'unit', 'spread', 'total', 'money line']
        for keyword in keywords:
            if keyword in content.lower():
                # Found picks-related content
                idx = content.lower().index(keyword)
                # Get a good chunk around this area
                start = max(0, idx - 1000)
                end = min(len(content), idx + 5000)
                picks_section = content[start:end]
                break
        
        # Calculate hash
        return hashlib.md5(picks_section.encode()).hexdigest()
    
    def send_discord_alert(self):
        """Send a simple alert to Discord"""
        try:
            embed = {
                "title": "🚨 New Bruce Marshall Pick Available!",
                "description": "Bruce Marshall has posted a new pick on SportsLine",
                "color": 0xFF0000,  # Red for urgency
                "fields": [
                    {
                        "name": "🔗 View Pick",
                        "value": f"[**Click here to see the new pick**]({self.expert_url})",
                        "inline": False
                    },
                    {
                        "name": "⏰ Alert Time",
                        "value": datetime.now().strftime('%I:%M %p EST'),
                        "inline": True
                    }
                ],
                "footer": {
                    "text": "SportsLine Premium Monitor",
                    "icon_url": "https://www.sportsline.com/favicon.ico"
                }
            }
            
            payload = {
                "username": "SportsLine Alert",
                "content": "@everyone New pick from Bruce Marshall!",  # Optional ping
                "embeds": [embed]
            }
            
            response = requests.post(self.webhook, json=payload)
            response.raise_for_status()
            
            print("✅ Alert sent to Discord!")
            return True
            
        except Exception as e:
            print(f"❌ Discord error: {e}")
            return False
    
    def run(self):
        """Main monitoring logic"""
        print("="*50)
        print(f"SportsLine Monitor - {datetime.now().strftime('%I:%M %p')}")
        print("="*50)
        
        # Check credentials
        if not self.email or not self.password:
            print("❌ Missing SportsLine credentials")
            return
        
        if not self.webhook:
            print("❌ Missing Discord webhook")
            return
        
        # Login
        if not self.login():
            print("❌ Could not login")
            return
        
        # Get page content
        content = self.get_page_content()
        if not content:
            print("❌ Could not get page content")
            return
        
        # Calculate hash
        current_hash = self.calculate_hash(content)
        if not current_hash:
            print("❌ Could not calculate page hash")
            return
        
        print(f"Current hash: {current_hash[:8]}...")
        print(f"Previous hash: {self.last_hash[:8]}..." if self.last_hash else "No previous hash")
        
        # Check if page changed
        if self.last_hash and current_hash != self.last_hash:
            print("🎯 PAGE CHANGED - New content detected!")
            
            # Send Discord alert
            if self.send_discord_alert():
                # Save new hash only if alert was sent successfully
                self.save_state(current_hash)
                print("✅ State updated")
            else:
                print("⚠️ Alert failed, will retry next run")
        
        elif not self.last_hash:
            print("📝 First run - saving initial state")
            self.save_state(current_hash)
        
        else:
            print("✅ No changes detected")
        
        print("="*50)
        print("Check complete")

if __name__ == "__main__":
    monitor = SimpleMonitor()
    monitor.run()