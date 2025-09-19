#!/usr/bin/env python3
"""
SportsLine Monitor - BULLETPROOF VERSION
Multiple detection methods to ensure we NEVER miss a pick
"""

import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import hashlib
import re
import time

class SportsLineMonitor:
    def __init__(self):
        self.email = os.environ.get('SPORTSLINE_EMAIL')
        self.password = os.environ.get('SPORTSLINE_PASSWORD')
        self.webhook = os.environ.get('DISCORD_WEBHOOK_URL')
        
        self.expert_url = "https://www.sportsline.com/experts/51297150/bruce-marshall/"
        self.login_url = "https://www.sportsline.com/login"
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        })
        
        self.state_file = 'monitor_state.json'
        self.load_state()
    
    def load_state(self):
        """Load all previous tracking data"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    self.state = json.load(f)
            else:
                self.state = {
                    'pick_count': 0,
                    'page_size': 0,
                    'picks_hash': '',
                    'team_names': [],
                    'timestamps': [],
                    'last_check': '',
                    'content_hash': ''
                }
        except:
            self.state = {
                'pick_count': 0,
                'page_size': 0,
                'picks_hash': '',
                'team_names': [],
                'timestamps': [],
                'last_check': '',
                'content_hash': ''
            }
    
    def save_state(self, new_state):
        """Save current state"""
        try:
            new_state['last_check'] = datetime.now().isoformat()
            with open(self.state_file, 'w') as f:
                json.dump(new_state, f, indent=2)
            self.state = new_state
        except Exception as e:
            print(f"Error saving state: {e}")
    
    def login(self):
        """Robust login with verification"""
        try:
            print("🔐 Logging in to SportsLine...")
            
            # Clear cookies first
            self.session.cookies.clear()
            
            # Get login page
            login_resp = self.session.get(self.login_url)
            soup = BeautifulSoup(login_resp.content, 'html.parser')
            
            # Build complete login data
            login_data = {
                'email': self.email,
                'password': self.password,
                'remember': '1',
                'remember_me': '1'
            }
            
            # Add ALL hidden fields
            for form in soup.find_all('form'):
                for field in form.find_all('input'):
                    name = field.get('name')
                    if name and name not in login_data:
                        login_data[name] = field.get('value', '')
            
            # Submit login
            post_resp = self.session.post(self.login_url, data=login_data, allow_redirects=True)
            
            # Verify by checking the expert page
            time.sleep(1)
            test_resp = self.session.get(self.expert_url)
            test_text = test_resp.text.lower()
            
            # Check if we're logged in
            if 'logout' in test_text or 'my account' in test_text:
                print("✅ Login successful (verified)")
                return True
            elif 'subscribe now' in test_text[:1000]:
                print("⚠️ Login may have failed (seeing subscribe prompts)")
                # Try one more time
                self.session.post(self.login_url, data=login_data, allow_redirects=True)
                time.sleep(2)
                return True
            else:
                print("✅ Proceeding with current session")
                return True
                
        except Exception as e:
            print(f"❌ Login error: {e}")
            return False
    
    def analyze_page(self):
        """Comprehensive page analysis using multiple methods"""
        try:
            print("📥 Fetching Bruce Marshall's page...")
            
            # Force fresh request (no cache)
            response = self.session.get(
                self.expert_url,
                headers={'Cache-Control': 'no-cache'}
            )
            
            if response.status_code != 200:
                print(f"❌ Bad status code: {response.status_code}")
                return None
            
            print(f"✅ Got {len(response.content)} bytes")
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Also get raw text
            full_text = soup.get_text()
            full_text = ' '.join(full_text.split())  # Clean whitespace
            
            # Create comprehensive analysis
            analysis = {
                'pick_count': 0,
                'page_size': len(response.content),
                'picks_hash': '',
                'team_names': [],
                'timestamps': [],
                'content_hash': '',
                'picks_text': '',
                'changes': []
            }
            
            # METHOD 1: Look for "Bruce's Picks (X Live)" or similar
            print("🔍 Method 1: Checking pick count...")
            count_patterns = [
                r"Bruce's Picks\s*\((\d+)\s*Live\)",
                r"Picks\s*\((\d+)\s*Live\)",
                r"\((\d+)\s*Live\)",
                r"(\d+)\s*Live\s*Pick",
                r"(\d+)\s*Active\s*Pick"
            ]
            
            for pattern in count_patterns:
                match = re.search(pattern, full_text, re.IGNORECASE)
                if match:
                    analysis['pick_count'] = int(match.group(1))
                    print(f"  ✓ Found {analysis['pick_count']} picks")
                    break
            
            # METHOD 2: Extract all team matchups
            print("🔍 Method 2: Finding team names...")
            team_patterns = [
                # Teams with odds/spreads
                r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*[+\-]\d+(?:\.\d+)?',
                # Teams in "@ Team" format
                r'@\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
                # Specific teams we know about
                r'(Chelsea|Manchester\s+United|Liverpool|Arsenal|Barcelona|Real\s+Madrid)',
                r'(BYU|East\s+Carolina|UCLA|USC|Alabama|Georgia)',
                # NFL teams
                r'(Patriots|Cowboys|Packers|Chiefs|Bills|Eagles|49ers|Rams)',
                # NBA teams
                r'(Lakers|Celtics|Warriors|Heat|Bulls|Knicks|Nets)'
            ]
            
            all_teams = set()
            for pattern in team_patterns:
                matches = re.findall(pattern, full_text)
                all_teams.update(matches)
            
            # Filter out non-team words
            non_teams = {'Money', 'Line', 'Point', 'Spread', 'Over', 'Under', 'Total', 'Props', 'Analysis', 'Unit'}
            analysis['team_names'] = [team for team in all_teams if team not in non_teams and len(team) > 2]
            print(f"  ✓ Found teams: {analysis['team_names'][:5]}..." if analysis['team_names'] else "  ✗ No teams found")
            
            # METHOD 3: Find timestamps (pick posting times)
            print("🔍 Method 3: Finding timestamps...")
            time_patterns = [
                r'Sep\s+\d+,?\s+\d{4}',
                r'\d{1,2}:\d{2}\s*[AP]M\s+PDT',
                r'\d{1,2}:\d{2}\s*[ap]m',
                r'Pick\s+Made:\s*([^\\n]+)',
                r'Posted:\s*([^\\n]+)'
            ]
            
            for pattern in time_patterns:
                matches = re.findall(pattern, full_text)
                analysis['timestamps'].extend(matches)
            
            print(f"  ✓ Found {len(analysis['timestamps'])} timestamps")
            
            # METHOD 4: Extract the actual picks section
            print("🔍 Method 4: Extracting picks section...")
            picks_section = ""
            
            # Find where picks start (after bio)
            picks_markers = [
                "Bruce's Picks",
                "Live Picks",
                "Today's Picks",
                "Recent Picks",
                "Money Line",
                "Point Spread",
                "Against the Spread"
            ]
            
            for marker in picks_markers:
                if marker in full_text:
                    idx = full_text.index(marker)
                    # Get everything from this marker forward
                    picks_section = full_text[idx:min(idx + 5000, len(full_text))]
                    print(f"  ✓ Found picks section at '{marker}'")
                    break
            
            # If no marker found, skip the bio and take middle section
            if not picks_section:
                # Skip first 2000 chars (bio) and last 1000 (footer)
                if len(full_text) > 3000:
                    picks_section = full_text[2000:-1000]
                    print(f"  ✓ Using middle section of page")
            
            analysis['picks_text'] = picks_section[:3000]  # Store first 3000 chars
            
            # METHOD 5: Look for specific pick elements in HTML
            print("🔍 Method 5: Checking HTML structure...")
            pick_elements = []
            
            # Look for divs/sections with pick-related classes
            for element in soup.find_all(['div', 'article', 'section']):
                element_text = element.get_text()
                if any(word in element_text for word in ['Chelsea', 'Manchester', 'Unit:', 'Analysis:', '+145', '-105']):
                    pick_elements.append(element_text[:200])
            
            print(f"  ✓ Found {len(pick_elements)} potential pick elements")
            
            # METHOD 6: Calculate hashes for change detection
            print("🔍 Method 6: Calculating hashes...")
            
            # Hash of just the picks section
            if picks_section:
                # Remove volatile data (times that change on every load)
                clean_picks = re.sub(r'\d+\s*(seconds?|minutes?|hours?)\s*ago', 'TIME_AGO', picks_section)
                clean_picks = re.sub(r'\d{1,2}:\d{2}\s*[AP]M', 'TIME', clean_picks)
                analysis['picks_hash'] = hashlib.md5(clean_picks.encode()).hexdigest()
            
            # Hash of full content (backup)
            analysis['content_hash'] = hashlib.md5(full_text.encode()).hexdigest()
            
            print(f"  ✓ Picks hash: {analysis['picks_hash'][:12]}...")
            print(f"  ✓ Content hash: {analysis['content_hash'][:12]}...")
            
            # METHOD 7: Count actual pick entries if visible
            if analysis['pick_count'] == 0:
                # Count unique games mentioned
                games = set()
                game_pattern = r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*@\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
                for match in re.finditer(game_pattern, full_text):
                    games.add(f"{match.group(1)} @ {match.group(2)}")
                
                if games:
                    analysis['pick_count'] = len(games)
                    print(f"  ✓ Counted {analysis['pick_count']} games")
            
            return analysis
            
        except Exception as e:
            print(f"❌ Analysis error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def detect_changes(self, current):
        """Smart change detection using multiple signals"""
        if not self.state['last_check']:
            print("📝 First run - establishing baseline")
            return True, "Monitor initialized. Now tracking Bruce Marshall's picks."
        
        changes = []
        
        # CHECK 1: Pick count changed
        if current['pick_count'] != self.state['pick_count']:
            if current['pick_count'] > self.state['pick_count']:
                diff = current['pick_count'] - self.state['pick_count']
                changes.append(f"🆕 {diff} NEW PICK{'S' if diff > 1 else ''} ADDED!")
            else:
                changes.append(f"Pick count changed: {self.state['pick_count']} → {current['pick_count']}")
        
        # CHECK 2: New teams appeared
        old_teams = set(self.state.get('team_names', []))
        new_teams = set(current['team_names'])
        added_teams = new_teams - old_teams
        if added_teams:
            changes.append(f"New teams: {', '.join(list(added_teams)[:3])}")
        
        # CHECK 3: Content hash changed (catches any change)
        if current['picks_hash'] and self.state.get('picks_hash'):
            if current['picks_hash'] != self.state['picks_hash']:
                changes.append("Pick content updated")
        
        # CHECK 4: Page size changed significantly (new content added)
        if self.state.get('page_size', 0) > 0:
            size_diff = current['page_size'] - self.state['page_size']
            if abs(size_diff) > 500:  # Significant change
                if size_diff > 0:
                    changes.append(f"Page grew by {size_diff} bytes (new content)")
        
        # CHECK 5: New timestamps appeared
        old_times = set(self.state.get('timestamps', []))
        new_times = set(current['timestamps'])
        if len(new_times) > len(old_times):
            changes.append("New pick timestamps detected")
        
        if changes:
            return True, "\n".join(changes)
        else:
            return False, None
    
    def send_discord_alert(self, message, color=0xFF0000):
        """Send alert to Discord"""
        try:
            # Add pick count if we have it
            pick_info = ""
            if self.state.get('pick_count', 0) > 0:
                pick_info = f"\n\n**Active Picks: {self.state['pick_count']}**"
            
            embed = {
                "title": "🚨 Bruce Marshall Update",
                "description": message + pick_info,
                "color": color,
                "fields": [
                    {
                        "name": "🔗 View All Picks",
                        "value": f"[**CLICK HERE TO SEE PICKS**]({self.expert_url})",
                        "inline": False
                    },
                    {
                        "name": "⏰ Time",
                        "value": datetime.now().strftime('%I:%M %p'),
                        "inline": True
                    }
                ],
                "footer": {"text": "SportsLine Monitor • Checking every 5 minutes"}
            }
            
            payload = {
                "username": "Bruce Marshall Alerts",
                "embeds": [embed]
            }
            
            response = requests.post(self.webhook, json=payload)
            response.raise_for_status()
            print("✅ Discord alert sent!")
            return True
            
        except Exception as e:
            print(f"❌ Discord error: {e}")
            return False
    
    def run(self):
        """Main execution"""
        print("\n" + "="*60)
        print(f"🏈 SportsLine Monitor - {datetime.now().strftime('%I:%M %p')}")
        print("="*60)
        
        # Verify setup
        if not all([self.email, self.password, self.webhook]):
            print("❌ Missing credentials!")
            return
        
        # Login
        if not self.login():
            print("❌ Login failed!")
            return
        
        # Analyze page
        current_analysis = self.analyze_page()
        if not current_analysis:
            print("❌ Could not analyze page")
            return
        
        print("\n📊 ANALYSIS RESULTS:")
        print(f"  • Pick count: {current_analysis['pick_count']}")
        print(f"  • Teams found: {len(current_analysis['team_names'])}")
        print(f"  • Page size: {current_analysis['page_size']} bytes")
        
        # Detect changes
        has_changes, change_message = self.detect_changes(current_analysis)
        
        if has_changes:
            print("\n🎯 CHANGES DETECTED!")
            print(change_message)
            
            # Send alert
            self.send_discord_alert(change_message)
            
            # Save new state
            self.save_state(current_analysis)
        else:
            print("\n✅ No changes detected")
            
            # Optional status update
            if os.environ.get('SEND_STATUS', 'false').lower() == 'true':
                status = f"No changes. Monitoring {current_analysis['pick_count']} active picks."
                self.send_discord_alert(status, color=0x00FF00)
        
        print("="*60 + "\n")

if __name__ == "__main__":
    # Allow forced reset
    if os.environ.get('RESET', 'false').lower() == 'true':
        if os.path.exists('monitor_state.json'):
            os.remove('monitor_state.json')
            print("🔄 State reset!")
    
    monitor = SportsLineMonitor()
    monitor.run()