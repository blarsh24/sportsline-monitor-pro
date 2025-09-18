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
        """Login to SportsLine"""
        try:
            print("Logging in...")
            
            # Get login page
            r = self.session.get(self.login_url)
            soup = BeautifulSoup(r.content, 'html.parser')
            
            # Setup login data
            data = {
                'email': self.email,
                'password': self.password
            }
            
            # Add any hidden fields from form
            form = soup.find('form')
            if form:
                for inp in form.find_all('input', type='hidden'):
                    if inp.get('name'):
                        data[inp.get('name')] = inp.get('value', '')
            
            # Login
            self.session.post(self.login_url, data=data)
            print("Login attempt completed")
            return True
        except Exception as e:
            print(f"Login error: {e}")
            return False
    
    def get_picks_from_page(self):
        """Get the actual picks from the page"""
        try:
            print("Fetching picks page...")
            r = self.session.get(self.expert_url)
            soup = BeautifulSoup(r.content, 'html.parser')
            
            picks = []
            
            # Method 1: Look for pick articles/divs
            pick_containers = soup.find_all(['article', 'div'], class_=lambda x: x and ('pick' in str(x).lower() or 'play' in str(x).lower()))
            
            for container in pick_containers[:10]:
                pick_data = self.extract_pick_from_container(container)
                if pick_data:
                    picks.append(pick_data)
            
            # Method 2: Look in tables
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')[1:]  # Skip header
                for row in rows[:10]:
                    pick_data = self.extract_pick_from_row(row)
                    if pick_data:
                        picks.append(pick_data)
            
            # Method 3: Search for patterns in text
            text = soup.get_text()
            text_picks = self.extract_picks_from_text(text)
            picks.extend(text_picks)
            
            # Clean and validate picks
            valid_picks = []
            for pick in picks:
                if self.is_valid_pick(pick):
                    valid_picks.append(pick)
            
            print(f"Found {len(valid_picks)} valid picks")
            return valid_picks
            
        except Exception as e:
            print(f"Error getting picks: {e}")
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
        """Fallback: extract picks from raw text"""
        picks = []
        
        # Clean the text
        text = re.sub(r'\s+', ' ', text)
        
        # Find all game patterns
        game_pattern = r'([A-Z][A-Za-z]{2,}(?:\s+[A-Za-z]+)?)\s+@\s+([A-Z][A-Za-z]{2,}(?:\s+[A-Za-z]+)?)'
        
        for match in re.finditer(game_pattern, text):
            team1 = match.group(1)
            team2 = match.group(2)
            
            # Validate teams
            if len(team1) < 3 or len(team2) < 3:
                continue
            if any(skip in (team1 + team2).lower() for skip in ['sportsline', 'cbs', 'copyright', 'privacy']):
                continue
            
            # Get context
            start = max(0, match.start() - 100)
            end = min(len(text), match.end() + 200)
            context = text[start:end]
            
            # Must have pick indicator
            if not re.search(r'(pick|play|bet|take)', context, re.I):
                continue
            
            game = f"{team1} @ {team2}"
            pick = team2  # Default
            
            # Try to find actual pick
            pick_match = re.search(r'(?:pick|play|take)\s+([A-Za-z\s]+?)(?:\s+[+-]|\.|$)', context, re.I)
            if pick_match:
                pick = pick_match.group(1).strip()
            
            picks.append({
                'game': game,
                'pick': pick,
                'odds': "Check Site",
                'units': "1",
                'confidence': "",
                'raw_text': context[:200]
            })
            
            if len(picks) >= 5:
                break
        
        return picks
    
    def is_valid_pick(self, pick):
        """Validate that this is a real sports pick"""
        if not pick or not pick.get('game'):
            return False
        
        game = pick['game'].lower()
        
        # Must not contain website junk
        junk = ['sportsline', 'cbs', 'interactive', '.com', 'copyright', 'privacy', 'terms']
        if any(j in game for j in junk):
            return False
        
        # Must have reasonable team names
        teams = game.split('@')
        if len(teams) != 2:
            return False
        
        for team in teams:
            team = team.strip()
            if len(team) < 3 or len(team) > 30:
                return False
        
        # Check if it's a known sport
        all_teams = game
        sports_keywords = [
            # NFL
            'patriots', 'bills', 'dolphins', 'jets', 'ravens', 'bengals', 'browns', 'steelers',
            'texans', 'colts', 'jaguars', 'titans', 'broncos', 'chiefs', 'raiders', 'chargers',
            'cowboys', 'giants', 'eagles', 'commanders', 'bears', 'lions', 'packers', 'vikings',
            'falcons', 'panthers', 'saints', 'buccaneers', '49ers', 'cardinals', 'rams', 'seahawks',
            # NBA
            'lakers', 'clippers', 'warriors', 'suns', 'kings', 'blazers', 'nuggets', 'jazz',
            'timberwolves', 'thunder', 'mavericks', 'rockets', 'grizzlies', 'pelicans', 'spurs',
            'celtics', 'nets', 'knicks', '76ers', 'raptors', 'heat', 'magic', 'hawks',
            'hornets', 'wizards', 'bulls', 'cavaliers', 'pistons', 'pacers', 'bucks',
            # MLB  
            'yankees', 'red sox', 'orioles', 'rays', 'blue jays', 'white sox', 'guardians',
            'tigers', 'royals', 'twins', 'astros', 'angels', 'athletics', 'mariners', 'rangers',
            'braves', 'marlins', 'mets', 'phillies', 'nationals', 'cubs', 'reds', 'brewers',
            'pirates', 'cardinals', 'dodgers', 'padres', 'giants', 'diamondbacks', 'rockies',
            # College
            'state', 'university', 'college', 'tech', 'alabama', 'georgia', 'ohio', 'michigan',
            'florida', 'texas', 'oklahoma', 'clemson', 'notre dame', 'usc', 'ucla'
        ]
        
        # Must contain at least one sports keyword
        if not any(keyword in all_teams for keyword in sports_keywords):
            return False
        
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
        print("\n" + "="*50)
        print(f"SportsLine Monitor - {datetime.now().strftime('%I:%M %p')}")
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