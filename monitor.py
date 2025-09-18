#!/usr/bin/env python3
"""
SportsLine Monitor - SIMPLIFIED & WORKING VERSION
Only sends real picks when they appear
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import time
from datetime import datetime
import re
import hashlib

class SportsLineMonitor:
    def __init__(self):
        self.email = os.environ.get('SPORTSLINE_EMAIL')
        self.password = os.environ.get('SPORTSLINE_PASSWORD')
        self.webhook = os.environ.get('DISCORD_WEBHOOK_URL')
        
        self.expert_url = "https://www.sportsline.com/experts/51297150/bruce-marshall/"
        self.login_url = "https://www.sportsline.com/login"
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
        })
        
        # Load previous picks to avoid duplicates
        self.state_file = 'picks_seen.json'
        self.seen_picks = self.load_seen_picks()
        
    def load_seen_picks(self):
        """Load picks we've already sent"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return set(json.load(f))
        except:
            pass
        return set()
    
    def save_seen_picks(self):
        """Save picks we've sent"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(list(self.seen_picks)[-500:], f)  # Keep last 500
        except:
            pass
    
    def login(self):
        """Login to SportsLine - FIXED VERSION"""
        try:
            print("Logging in...")
            
            # Step 1: Get login page to get cookies and tokens
            login_page = self.session.get(self.login_url)
            soup = BeautifulSoup(login_page.content, 'html.parser')
            
            # Step 2: Find the login form and get all fields
            data = {
                'email': self.email,
                'password': self.password,
                'remember': '1',
                'remember_me': '1'
            }
            
            # Add ALL hidden fields from the form
            forms = soup.find_all('form')
            for form in forms:
                # Find the login form (usually has email/password fields)
                if form.find('input', {'type': 'email'}) or form.find('input', {'name': 'email'}):
                    for inp in form.find_all('input'):
                        name = inp.get('name')
                        value = inp.get('value', '')
                        if name and name not in data:
                            data[name] = value
                    break
            
            print(f"Login data fields: {list(data.keys())}")
            
            # Step 3: Submit login
            response = self.session.post(
                self.login_url,
                data=data,
                allow_redirects=True
            )
            
            # Step 4: Verify login worked
            time.sleep(2)  # Give it a moment
            
            # Check if we can access the expert page
            test_page = self.session.get(self.expert_url)
            test_soup = BeautifulSoup(test_page.content, 'html.parser')
            test_text = test_soup.get_text().lower()
            
            # Check for login success indicators
            if 'log out' in test_text or 'logout' in test_text or 'my account' in test_text:
                print("✅ Login successful!")
                return True
            elif 'subscribe now' in test_text or 'join now' in test_text:
                print("❌ Login failed - still seeing subscribe prompts")
                print("Trying alternative login method...")
                
                # Alternative: Try to find and click login button
                return self.alternative_login()
            else:
                print("⚠️ Login status unclear, proceeding anyway")
                return True
                
        except Exception as e:
            print(f"Login error: {e}")
            return False
    
    def alternative_login(self):
        """Alternative login approach"""
        try:
            # Fresh session
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.sportsline.com/'
            })
            
            # Get main page first (sometimes needed for cookies)
            self.session.get('https://www.sportsline.com/')
            time.sleep(1)
            
            # Now get login page
            login_resp = self.session.get(self.login_url)
            soup = BeautifulSoup(login_resp.content, 'html.parser')
            
            # Build login data more carefully
            login_data = {}
            
            # Find the actual form
            form = soup.find('form', {'method': 'post'}) or soup.find('form')
            if form:
                # Get form action URL
                action = form.get('action', self.login_url)
                if not action.startswith('http'):
                    action = 'https://www.sportsline.com' + action
                
                # Get all inputs
                for inp in form.find_all(['input', 'button']):
                    name = inp.get('name')
                    if name:
                        if name == 'email' or 'email' in name.lower():
                            login_data[name] = self.email
                        elif name == 'password' or 'pass' in name.lower():
                            login_data[name] = self.password
                        else:
                            login_data[name] = inp.get('value', '')
                
                # Post to the form action
                resp = self.session.post(action, data=login_data, allow_redirects=True)
                
                # Check success
                if 'logout' in resp.text.lower() or len(resp.text) > 100000:
                    print("✅ Alternative login successful!")
                    return True
            
            print("❌ Alternative login also failed")
            return False
            
        except Exception as e:
            print(f"Alternative login error: {e}")
            return False
    
    def get_picks_from_page(self):
        """Get the actual picks from the page - IMPROVED"""
        try:
            print("Fetching picks page...")
            r = self.session.get(self.expert_url)
            print(f"Page status: {r.status_code}")
            print(f"Page size: {len(r.content)} bytes")
            
            soup = BeautifulSoup(r.content, 'html.parser')
            
            # Debug: Check if we're logged in
            page_text = soup.get_text()
            if 'subscribe now' in page_text.lower() or 'join now' in page_text.lower():
                print("⚠️ WARNING: Might not be logged in properly (seeing subscribe prompts)")
            
            # DEBUG: Let's see what's actually on the page
            print("\n=== PAGE CONTENT SAMPLE ===")
            # Look for anything that might be a pick
            sample = page_text[:2000].replace('\n', ' ').replace('\t', ' ')
            print(f"First 2000 chars: {sample}")
            
            # Look for specific sections
            print("\n=== SEARCHING FOR PICKS ===")
            
            picks = []
            
            # Method 1: Look for specific pick elements
            # Try different class names that might contain picks
            possible_classes = ['pick', 'play', 'bet', 'prediction', 'selection', 'expert-pick', 
                               'pick-card', 'game-pick', 'best-bet', 'premium-pick']
            
            for class_name in possible_classes:
                elements = soup.find_all(['div', 'article', 'section'], class_=re.compile(class_name, re.I))
                if elements:
                    print(f"Found {len(elements)} elements with class containing '{class_name}'")
                    for elem in elements[:3]:  # Check first 3
                        text = elem.get_text()[:200]
                        print(f"  Element text: {text}")
                        pick_data = self.extract_pick_from_container(elem)
                        if pick_data:
                            picks.append(pick_data)
            
            # Method 2: Look for picks in any div/article with game-like content
            all_divs = soup.find_all(['div', 'article'], limit=100)
            for div in all_divs:
                text = div.get_text()
                # Quick check if this might be a pick
                if '@' in text or ' vs ' in text.lower():
                    if any(word in text.lower() for word in ['pick', 'play', 'bet', 'unit']):
                        pick_data = self.extract_pick_from_container(div)
                        if pick_data:
                            picks.append(pick_data)
            
            # Method 3: Look in tables
            tables = soup.find_all('table')
            print(f"Found {len(tables)} tables")
            for i, table in enumerate(tables[:5]):
                print(f"Table {i+1} sample: {table.get_text()[:200]}")
                rows = table.find_all('tr')[1:]  # Skip header
                for row in rows[:10]:
                    pick_data = self.extract_pick_from_row(row)
                    if pick_data:
                        picks.append(pick_data)
            
            # Method 4: Last resort - search raw HTML for specific patterns
            html_text = str(soup)
            print(f"\nSearching raw HTML ({len(html_text)} characters)...")
            
            # Look for JSON data that might contain picks
            json_pattern = r'window\.__INITIAL_STATE__\s*=\s*({.*?});'
            json_match = re.search(json_pattern, html_text, re.DOTALL)
            if json_match:
                print("Found JSON data in page")
                try:
                    import json
                    data = json.loads(json_match.group(1))
                    print(f"JSON keys: {list(data.keys())[:10]}")
                except:
                    pass
            
            # Method 5: Search for patterns in text
            text = soup.get_text()
            # Remove excessive whitespace
            text = ' '.join(text.split())
            print(f"Searching cleaned text ({len(text)} characters)...")
            
            # Show a sample where we might expect picks
            if 'bruce marshall' in text.lower():
                idx = text.lower().index('bruce marshall')
                print(f"Content near 'Bruce Marshall': {text[idx:idx+500]}")
            
            text_picks = self.extract_picks_from_text(text)
            picks.extend(text_picks)
            
            # Clean and validate picks
            valid_picks = []
            seen = set()
            for pick in picks:
                if self.is_valid_pick(pick):
                    game_id = pick['game']
                    if game_id not in seen:
                        seen.add(game_id)
                        valid_picks.append(pick)
                        print(f"✓ Valid pick found: {pick['game']}")
                else:
                    if pick and pick.get('game'):
                        print(f"✗ Invalid pick filtered out: {pick['game']}")
            
            print(f"\nFound {len(picks)} total picks, {len(valid_picks)} valid unique picks")
            return valid_picks
            
        except Exception as e:
            print(f"Error getting picks: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def extract_pick_from_container(self, container):
        """Extract pick from a container element"""
        try:
            text = container.get_text()
            
            # Look for team vs team pattern
            match = re.search(r'([A-Z][A-Za-z\s\.]+?)\s+(?:@|vs\.?)\s+([A-Z][A-Za-z\s\.]+)', text)
            if not match:
                return None
            
            team1 = match.group(1).strip()
            team2 = match.group(2).strip()
            
            # Skip if it's not real teams
            if len(team1) < 3 or len(team2) < 3:
                return None
            if 'sportsline' in team1.lower() or 'sportsline' in team2.lower():
                return None
                
            game = f"{team1} @ {team2}"
            
            # Find the pick
            pick = team2  # Default
            pick_match = re.search(r'(?:Pick|Play|Take)\s+([A-Za-z\s\.]+)', text, re.I)
            if pick_match:
                pick = pick_match.group(1).strip()
            
            # Find spread
            spread_match = re.search(r'([+-]\d+\.?\d?)', text)
            if spread_match:
                pick += f" {spread_match.group(1)}"
            
            # Find odds
            odds = "N/A"
            odds_match = re.search(r'([+-]\d{3,4})(?!\d)', text)
            if odds_match:
                odds = odds_match.group(1)
            
            # Find units
            units = "1"
            units_match = re.search(r'(\d+\.?\d?)\s*units?', text, re.I)
            if units_match:
                units = units_match.group(1)
            
            # Find confidence
            confidence = ""
            if '5 star' in text.lower() or 'five star' in text.lower() or 'best bet' in text.lower():
                confidence = "⭐⭐⭐⭐⭐"
            elif '4 star' in text.lower():
                confidence = "⭐⭐⭐⭐"
            elif '3 star' in text.lower():
                confidence = "⭐⭐⭐"
            
            return {
                'game': game,
                'pick': pick,
                'odds': odds,
                'units': units,
                'confidence': confidence,
                'raw_text': text[:200]
            }
            
        except:
            return None
    
    def extract_pick_from_row(self, row):
        """Extract pick from table row"""
        try:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                return None
            
            # Usually: Game | Pick | Odds | Units
            game_text = cells[0].get_text().strip()
            
            # Parse game
            match = re.search(r'([A-Z][A-Za-z\s\.]+?)\s+(?:@|vs\.?)\s+([A-Z][A-Za-z\s\.]+)', game_text)
            if not match:
                return None
            
            team1 = match.group(1).strip()
            team2 = match.group(2).strip()
            
            if len(team1) < 3 or len(team2) < 3:
                return None
                
            game = f"{team1} @ {team2}"
            
            # Get other cells
            pick = cells[1].get_text().strip() if len(cells) > 1 else team2
            odds = cells[2].get_text().strip() if len(cells) > 2 else "N/A"
            units = cells[3].get_text().strip() if len(cells) > 3 else "1"
            
            return {
                'game': game,
                'pick': pick,
                'odds': odds,
                'units': units.replace('units', '').strip(),
                'confidence': "",
                'raw_text': row.get_text()[:200]
            }
            
        except:
            return None
    
    def extract_picks_from_text(self, text):
        """Fallback: extract picks from raw text - IMPROVED"""
        picks = []
        
        # Clean the text
        text = re.sub(r'\s+', ' ', text)
        
        print("DEBUG: Searching for game patterns...")
        
        # Multiple patterns to try
        patterns = [
            # Standard: Team @ Team
            r'([A-Z][A-Za-z]+(?:\s+[A-Za-z]+)?)\s+@\s+([A-Z][A-Za-z]+(?:\s+[A-Za-z]+)?)',
            # With city: City Team @ City Team  
            r'([A-Z][A-Za-z]+(?:\s+[A-Za-z]+)?(?:\s+[A-Za-z]+)?)\s+@\s+([A-Z][A-Za-z]+(?:\s+[A-Za-z]+)?(?:\s+[A-Za-z]+)?)',
            # Vs format: Team vs Team
            r'([A-Z][A-Za-z]+(?:\s+[A-Za-z]+)?)\s+vs\.?\s+([A-Z][A-Za-z]+(?:\s+[A-Za-z]+)?)'
        ]
        
        all_matches = []
        for pattern in patterns:
            matches = list(re.finditer(pattern, text))
            all_matches.extend(matches)
            if matches:
                print(f"DEBUG: Found {len(matches)} potential games with pattern")
        
        # Process matches
        seen_games = set()
        for match in all_matches:
            team1 = match.group(1).strip()
            team2 = match.group(2).strip()
            
            # Debug output
            print(f"DEBUG: Checking potential game: {team1} @ {team2}")
            
            # Basic validation
            if len(team1) < 3 or len(team2) < 3:
                print(f"  -> Rejected: team name too short")
                continue
            
            # Skip obvious non-teams
            skip_words = ['sportsline', 'cbs', 'interactive', 'copyright', 'privacy', 'terms', 
                         'conditions', 'subscribe', 'login', 'password', 'email', 'cookies']
            if any(skip in team1.lower() or skip in team2.lower() for skip in skip_words):
                print(f"  -> Rejected: contains website terms")
                continue
            
            game = f"{team1} @ {team2}"
            
            # Avoid duplicates
            if game in seen_games:
                continue
            seen_games.add(game)
            
            # Get context
            start = max(0, match.start() - 150)
            end = min(len(text), match.end() + 250)
            context = text[start:end]
            
            # Look for pick indicators nearby
            has_pick_indicator = any(word in context.lower() for word in 
                                    ['pick', 'play', 'bet', 'like', 'take', 'best bet', 'unit'])
            
            if not has_pick_indicator:
                print(f"  -> Rejected: no pick indicators nearby")
                continue
            
            print(f"  -> ACCEPTED: {game}")
            
            # Extract pick details
            pick = team2  # Default to home team
            
            # Try to find actual pick
            pick_patterns = [
                r'(?:pick|play|take|bet)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)',
                r'([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+[+-]\d+\.?\d?'
            ]
            
            for pp in pick_patterns:
                pm = re.search(pp, context, re.I)
                if pm:
                    potential_pick = pm.group(1).strip()
                    # Make sure it's one of the teams
                    if potential_pick.lower() in team1.lower() or potential_pick.lower() in team2.lower():
                        pick = potential_pick
                        break
            
            # Look for spread
            spread = ""
            spread_match = re.search(r'([+-]\d+\.?\d?)', context)
            if spread_match:
                spread = spread_match.group(1)
                pick = f"{pick} {spread}"
            
            # Look for odds
            odds = "N/A"
            odds_match = re.search(r'([+-]\d{3,4})(?!\d)', context)
            if odds_match:
                odds_val = int(odds_match.group(1))
                if -2000 < odds_val < 2000:  # Reasonable odds range
                    odds = odds_match.group(1)
            
            # Look for units
            units = "1"
            units_match = re.search(r'(\d+\.?\d?)\s*units?', context, re.I)
            if units_match:
                units = units_match.group(1)
            
            # Look for confidence
            confidence = ""
            if any(conf in context.lower() for conf in ['best bet', '5 star', 'five star']):
                confidence = "⭐⭐⭐⭐⭐"
            elif '4 star' in context.lower():
                confidence = "⭐⭐⭐⭐"
            
            picks.append({
                'game': game,
                'pick': pick,
                'odds': odds,
                'units': units,
                'confidence': confidence,
                'raw_text': context[:200]
            })
            
            if len(picks) >= 10:  # Limit
                break
        
        print(f"DEBUG: Extracted {len(picks)} picks from text")
        return picks
    
    def is_valid_pick(self, pick):
        """Validate that this is a real sports pick - LESS STRICT"""
        if not pick or not pick.get('game'):
            return False
        
        game = pick['game'].lower()
        
        # Must not contain website junk
        junk = ['sportsline.com', 'cbs', 'interactive.com', 'copyright', 'privacy policy', 'terms of service']
        if any(j in game for j in junk):
            print(f"  Rejected '{pick['game']}': contains junk words")
            return False
        
        # Must have reasonable team names
        teams = game.split('@')
        if len(teams) != 2:
            print(f"  Rejected '{pick['game']}': not in Team @ Team format")
            return False
        
        for team in teams:
            team = team.strip()
            if len(team) < 3:
                print(f"  Rejected '{pick['game']}': team name too short")
                return False
            if len(team) > 40:
                print(f"  Rejected '{pick['game']}': team name too long")
                return False
        
        # For now, let's be less strict about requiring known teams
        # Just check if it looks sports-related
        sports_indicators = [
            # General sports terms
            'united', 'city', 'fc', 'athletic', 'real', 'sporting',
            # US cities
            'new york', 'los angeles', 'chicago', 'houston', 'philadelphia',
            'phoenix', 'san antonio', 'san diego', 'dallas', 'san jose',
            'detroit', 'boston', 'seattle', 'denver', 'washington',
            'miami', 'atlanta', 'oakland', 'kansas city', 'milwaukee',
            'minnesota', 'cleveland', 'tampa', 'pittsburgh', 'cincinnati',
            'baltimore', 'charlotte', 'orlando', 'portland', 'sacramento',
            # Common team names
            'state', 'university', 'college', 
            # NFL
            'patriots', 'bills', 'dolphins', 'jets', 'ravens', 'bengals', 'browns', 'steelers',
            'texans', 'colts', 'jaguars', 'titans', 'broncos', 'chiefs', 'raiders', 'chargers',
            'cowboys', 'giants', 'eagles', 'commanders', 'bears', 'lions', 'packers', 'vikings',
            # NBA
            'lakers', 'clippers', 'warriors', 'celtics', 'nets', 'knicks', 'heat', 'bulls',
            # MLB
            'yankees', 'mets', 'dodgers', 'giants', 'cubs', 'sox', 'astros', 'braves'
        ]
        
        # Check if at least one indicator is present
        has_indicator = any(indicator in game for indicator in sports_indicators)
        
        if not has_indicator:
            # Still accept if it looks like City vs City or Team vs Team
            if re.search(r'[A-Z][a-z]+', pick['game']):  # Has proper capitalization
                print(f"  Accepting '{pick['game']}': looks like proper team names")
                return True
            else:
                print(f"  Rejected '{pick['game']}': no sports indicators found")
                return False
        
        print(f"  Accepted '{pick['game']}': valid sports pick")
        return True
    
    def generate_pick_id(self, pick):
        """Generate unique ID for a pick"""
        content = f"{pick['game']}-{pick['pick']}-{datetime.now().strftime('%Y-%m-%d')}"
        return hashlib.md5(content.encode()).hexdigest()[:10]
    
    def send_to_discord(self, picks):
        """Send picks to Discord"""
        for pick in picks:
            try:
                # Generate ID
                pick_id = self.generate_pick_id(pick)
                
                # Skip if already sent
                if pick_id in self.seen_picks:
                    print(f"Skipping duplicate: {pick['game']}")
                    continue
                
                # Detect sport
                game_lower = pick['game'].lower()
                sport = "🏟️"
                if any(t in game_lower for t in ['patriots', 'bills', 'cowboys', 'chiefs', 'packers']):
                    sport = "🏈 NFL"
                elif any(t in game_lower for t in ['lakers', 'celtics', 'warriors', 'heat', 'knicks']):
                    sport = "🏀 NBA"
                elif any(t in game_lower for t in ['yankees', 'dodgers', 'astros', 'red sox']):
                    sport = "⚾ MLB"
                elif 'state' in game_lower or 'university' in game_lower:
                    sport = "🎓 College"
                
                # Build embed
                embed = {
                    "title": "🎯 New Bruce Marshall Pick",
                    "color": 0x00ff00 if not pick['confidence'] else 0xffd700,
                    "fields": [
                        {
                            "name": f"{sport} Game",
                            "value": f"**{pick['game']}**",
                            "inline": False
                        },
                        {
                            "name": "📊 Pick",
                            "value": f"**{pick['pick']}**",
                            "inline": True
                        },
                        {
                            "name": "💰 Odds",
                            "value": pick['odds'],
                            "inline": True
                        },
                        {
                            "name": "🎲 Units", 
                            "value": f"{pick['units']} unit{'s' if pick['units'] != '1' else ''}",
                            "inline": True
                        }
                    ],
                    "footer": {
                        "text": "Bruce Marshall • SportsLine Premium"
                    },
                    "timestamp": datetime.now().isoformat()
                }
                
                # Add confidence if present
                if pick['confidence']:
                    embed["fields"].insert(1, {
                        "name": "🔥 Confidence",
                        "value": pick['confidence'],
                        "inline": False
                    })
                
                payload = {
                    "username": "SportsLine Monitor",
                    "embeds": [embed]
                }
                
                r = requests.post(self.webhook, json=payload)
                r.raise_for_status()
                
                print(f"✅ Sent: {pick['game']} - {pick['pick']}")
                self.seen_picks.add(pick_id)
                
                time.sleep(2)
                
            except Exception as e:
                print(f"Discord error: {e}")
    
    def run(self):
        """Main execution"""
        # Fix timezone - use PST/PDT for west coast
        from datetime import datetime
        import time
        
        # Get current time in PST (UTC-8) or PDT (UTC-7)
        local_time = datetime.now()
        
        print("\n" + "="*50)
        print(f"SportsLine Monitor - {local_time.strftime('%I:%M %p')} Local Time")
        print("="*50)
        
        # Check credentials
        if not all([self.email, self.password, self.webhook]):
            print("❌ Missing credentials!")
            return
        
        # Login
        if not self.login():
            print("❌ Login failed")
            return
        
        # Get picks
        picks = self.get_picks_from_page()
        
        if not picks:
            print("No valid picks found")
            return
        
        # Filter new picks
        new_picks = []
        for pick in picks:
            pick_id = self.generate_pick_id(pick)
            if pick_id not in self.seen_picks:
                new_picks.append(pick)
        
        if new_picks:
            print(f"\n📤 Sending {len(new_picks)} new picks to Discord...")
            self.send_to_discord(new_picks)
        else:
            print("No new picks to send (all previously seen)")
        
        # Save state
        self.save_seen_picks()
        
        print("\n✅ Check complete")

if __name__ == "__main__":
    monitor = SportsLineMonitor()
    monitor.run()