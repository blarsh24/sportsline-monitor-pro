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
        
        # Control whether to send status updates (can be turned off if too noisy)
        self.send_status_updates = os.environ.get('SEND_STATUS_UPDATES', 'true').lower() == 'true'
        
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
        
        # Remove timestamps and dynamic content that changes every load
        # This might be causing false "no change" detections
        cleaned_content = content
        
        # Remove common dynamic elements
        # Remove times (like "2 hours ago", "posted at 3:45 PM", etc)
        cleaned_content = re.sub(r'\d{1,2}:\d{2}\s*(AM|PM|am|pm)', '', cleaned_content)
        cleaned_content = re.sub(r'\d+\s*(hours?|minutes?|seconds?)\s*ago', '', cleaned_content)
        cleaned_content = re.sub(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)', '', cleaned_content)
        
        # Remove any long number sequences (these might be IDs that change)
        cleaned_content = re.sub(r'\d{10,}', '', cleaned_content)
        
        # Focus on the actual picks content
        # Look for pick-related content and extract a good chunk
        picks_section = cleaned_content
        
        # Try to find the picks area more aggressively
        keywords = ['pick', 'play', 'bet', 'unit', 'spread', 'total', 'money line', 
                   'best bet', 'recommendation', 'lean', 'over', 'under']
        
        found_picks = False
        for keyword in keywords:
            if keyword in cleaned_content.lower():
                # Found picks-related content
                idx = cleaned_content.lower().index(keyword)
                # Get a larger chunk around this area
                start = max(0, idx - 2000)
                end = min(len(cleaned_content), idx + 8000)
                picks_section = cleaned_content[start:end]
                found_picks = True
                print(f"Found picks section using keyword '{keyword}'")
                break
        
        if not found_picks:
            print("⚠️ WARNING: No pick keywords found - using full content")
            picks_section = cleaned_content
        
        # Show what we're hashing (first 200 chars)
        print(f"Hashing content sample: {picks_section[:200]}...")
        
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
    
    def send_status_update(self, current_hash, changed=False):
        """Send status update to Discord"""
        try:
            if changed:
                # Already handled by send_discord_alert
                return
            
            # Send "no changes" status update
            embed = {
                "title": "✅ Monitor Status: Active",
                "description": "No new picks found",
                "color": 0x00FF00,  # Green for all good
                "fields": [
                    {
                        "name": "📊 Status",
                        "value": "Page unchanged - no new picks",
                        "inline": False
                    },
                    {
                        "name": "🔍 Current Hash",
                        "value": f"`{current_hash[:12]}...`",
                        "inline": True
                    },
                    {
                        "name": "📝 Previous Hash", 
                        "value": f"`{self.last_hash[:12]}...`" if self.last_hash else "First run",
                        "inline": True
                    },
                    {
                        "name": "⏰ Check Time",
                        "value": datetime.now().strftime('%I:%M %p EST'),
                        "inline": True
                    },
                    {
                        "name": "📅 Last Change",
                        "value": self.last_check if self.last_check else "Unknown",
                        "inline": True
                    }
                ],
                "footer": {
                    "text": "Next check in 5 minutes",
                    "icon_url": "https://www.sportsline.com/favicon.ico"
                }
            }
            
            payload = {
                "username": "SportsLine Monitor",
                "embeds": [embed]
            }
            
            response = requests.post(self.webhook, json=payload)
            response.raise_for_status()
            
            print("✅ Status update sent to Discord")
            return True
            
        except Exception as e:
            print(f"⚠️ Could not send status update: {e}")
            return False
    
    def run(self):
        """Main monitoring logic"""
        print("="*50)
        print(f"SportsLine Monitor - {datetime.now().strftime('%I:%M %p')}")
        print("="*50)
        
        # Check if we should force an alert (for testing)
        force_alert = os.environ.get('FORCE_ALERT', 'false').lower() == 'true'
        if force_alert:
            print("⚠️ FORCE_ALERT is enabled - will send alert regardless")
        
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
        
        print(f"Current hash: {current_hash[:16]}...")
        print(f"Previous hash: {self.last_hash[:16]}..." if self.last_hash else "No previous hash")
        
        # Check for actual text differences (backup check)
        major_change = False
        if self.last_hash:
            # Check if hashes are different
            if current_hash != self.last_hash:
                major_change = True
                print(f"📊 Hash difference detected!")
                print(f"   Old: {self.last_hash[:16]}")
                print(f"   New: {current_hash[:16]}")
        
        # Check if page changed OR force alert
        if force_alert or (self.last_hash and (current_hash != self.last_hash or major_change)):
            if force_alert:
                print("🔥 FORCING ALERT (test mode)")
            else:
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
            # Send initial status
            if self.send_status_updates:
                self.send_status_update(current_hash)
        
        else:
            print("✅ No changes detected")
            # Show why they match
            print(f"   Hashes match: {current_hash[:16]} == {self.last_hash[:16]}")
            # Send status update (if enabled)
            if self.send_status_updates:
                self.send_status_update(current_hash)
        
        print("="*50)
        print("Check complete")

if __name__ == "__main__":
    # Check for reset flag
    if os.environ.get('RESET_STATE', 'false').lower() == 'true':
        print("🔄 RESETTING STATE FILE")
        if os.path.exists('page_state.json'):
            os.remove('page_state.json')
            print("✅ State file deleted - next run will be treated as first run")
    
    monitor = SimpleMonitor()
    monitor.run()