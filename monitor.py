#!/usr/bin/env python3
"""
SportsLine Monitor - WORKING VERSION
No syntax errors, properly cleaned output
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
        
        self.state_file = 'picks_seen.json'
        self.seen_picks = self.load_seen_picks()
    
    def load_seen_picks(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return set(json.load(f))
        except:
            pass
        return set()
    
    def save_seen_picks(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump(list(self.seen_picks)[-500:], f)
        except:
            pass
    
    def login(self):
        try:
            print("Logging in...")
            login_page = self.session.get(self.login_url)
            soup = BeautifulSoup(login_page.content, 'html.parser')
            
            data = {
                'email': self.email,
                'password': self.password,
                'remember': '1',
                'remember_me': '1'
            }
            
            form = soup.find('form')
            if form:
                for inp in form.find_all('input'):
                    name = inp.get('name')
                    if name and name not in data:
                        data[name] = inp.get('value', '')
            
            response = self.session.post(self.login_url, data=data, allow_redirects=True)
            
            if 'logout' in response.text.lower():
                print("✅ Login successful!")
                return True
            else:
                print("⚠️ Login uncertain, continuing...")
                return True
                
        except Exception as e:
            print(f"Login error: {e}")
            return False
    
    def clean_text(self, text):
        """Remove all junk from text"""
        if not text:
            return ""
        
        # Remove common junk
        junk_words = ['UTC', 'Money Line', 'Point Spread', 'Over', 'Under', 
                      'Subscri', 'LAST', 'Total', 'Spread']
        
        for junk in junk_words:
            text = text.replace(junk, '')
        
        # Remove excessive numbers
        text = re.sub(r'\+\d{5,}', '', text)  # Remove numbers with 5+ digits
        text = re.sub(r'-\d{5,}', '', text)
        
        # Clean whitespace
        text = ' '.join(text.split())
        
        return text.strip()
    
    def extract_picks(self):
        """Main function to extract picks from page"""
        try:
            print("Fetching picks page...")
            response = self.session.get(self.expert_url)
            print(f"Page status: {response.status_code}")
            print(f"Page size: {len(response.content)} bytes")
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Get all text
            full_text = soup.get_text()
            full_text = ' '.join(full_text.split())
            
            print(f"Searching {len(full_text)} characters...")
            
            picks = []
            
            # Find all potential games
            game_patterns = [
                r'([A-Z][A-Za-z\.\s]{2,25}?)\s*@\s*([A-Z][A-Za-z\.\s]{2,25})',
                r'([A-Z][A-Za-z\.\s]{2,25}?)\s+vs\.?\s+([A-Z][A-Za-z\.\s]{2,25})'
            ]
            
            found_games = []
            
            for pattern in game_patterns:
                matches = re.finditer(pattern, full_text)
                for match in matches:
                    team1 = self.clean_text(match.group(1))
                    team2 = self.clean_text(match.group(2))
                    
                    # Skip invalid teams
                    if not team1 or not team2:
                        continue
                    if len(team1) < 3 or len(team2) < 3:
                        continue
                    if len(team1) > 30 or len(team2) > 30:
                        continue
                    
                    # Skip website junk
                    skip_words = ['sportsline', 'cbs', 'interactive', 'copyright', 
                                  'privacy', 'terms', 'cookie', 'login']
                    if any(word in team1.lower() for word in skip_words):
                        continue
                    if any(word in team2.lower() for word in skip_words):
                        continue
                    
                    # Get context
                    start = max(0, match.start() - 300)
                    end = min(len(full_text), match.end() + 300)
                    context = full_text[start:end]
                    
                    # Check if this is a pick
                    if not any(word in context.lower() for word in ['pick', 'play', 'bet', 'unit']):
                        continue
                    
                    found_games.append({
                        'team1': team1,
                        'team2': team2,
                        'context': context
                    })
            
            # Process found games
            seen = set()
            for game_info in found_games:
                team1 = game_info['team1']
                team2 = game_info['team2']
                context = game_info['context']
                
                game_str = f"{team1} @ {team2}"
                
                if game_str in seen:
                    continue
                seen.add(game_str)
                
                # Extract pick details
                pick_team = team2  # Default
                
                # Look for actual pick
                for team in [team1, team2]:
                    if re.search(rf'(?:pick|play|take)\s+{re.escape(team)}', context, re.I):
                        pick_team = team
                        break
                
                # Look for spread
                spread = ""
                spread_match = re.search(r'([+-]\d+\.?\d?)(?:\s|$)', context)
                if spread_match:
                    spread_val = spread_match.group(1)
                    try:
                        val = float(spread_val)
                        if -50 < val < 50:
                            spread = spread_val
                    except:
                        pass
                
                if spread:
                    pick_team = f"{pick_team} {spread}"
                
                # Look for odds
                odds = "N/A"
                odds_match = re.search(r'([+-]\d{3,4})(?!\d)', context)
                if odds_match:
                    try:
                        val = int(odds_match.group(1))
                        if -2000 < val < 2000:
                            odds = odds_match.group(1)
                    except:
                        pass
                
                # Look for units
                units = "1"
                units_match = re.search(r'(\d+\.?\d?)\s*units?', context, re.I)
                if units_match:
                    try:
                        val = float(units_match.group(1))
                        if 0 < val <= 10:
                            units = units_match.group(1)
                    except:
                        pass
                
                pick = {
                    'game': game_str,
                    'pick': pick_team,
                    'odds': odds,
                    'units': units
                }
                
                picks.append(pick)
                print(f"Found: {game_str} -> {pick_team}")
            
            return picks
            
        except Exception as e:
            print(f"Error extracting picks: {e}")
            return []
    
    def generate_pick_id(self, pick):
        content = f"{pick['game']}-{pick['pick']}-{datetime.now().strftime('%Y-%m-%d')}"
        return hashlib.md5(content.encode()).hexdigest()[:10]
    
    def send_to_discord(self, picks):
        for pick in picks:
            try:
                pick_id = self.generate_pick_id(pick)
                
                if pick_id in self.seen_picks:
                    print(f"Skipping duplicate: {pick['game']}")
                    continue
                
                # Determine sport
                game_lower = pick['game'].lower()
                sport = "🏟️"
                
                # Check for known teams
                nfl_teams = ['patriots', 'bills', 'cowboys', 'packers', 'chiefs', 'eagles', 'rams']
                nba_teams = ['lakers', 'celtics', 'warriors', 'heat', 'bulls', 'knicks']
                mlb_teams = ['yankees', 'dodgers', 'astros', 'angels', 'mets', 'cubs']
                soccer_teams = ['barcelona', 'manchester', 'liverpool', 'chelsea', 'arsenal']
                
                if any(team in game_lower for team in nfl_teams):
                    sport = "🏈 NFL"
                elif any(team in game_lower for team in nba_teams):
                    sport = "🏀 NBA"
                elif any(team in game_lower for team in mlb_teams):
                    sport = "⚾ MLB"
                elif any(team in game_lower for team in soccer_teams):
                    sport = "⚽ Soccer"
                elif 'college' in game_lower or 'state' in game_lower or 'university' in game_lower:
                    sport = "🎓 College"
                
                embed = {
                    "title": "🎯 New Bruce Marshall Pick",
                    "color": 0x00ff00,
                    "fields": [
                        {"name": f"{sport} Game", "value": f"**{pick['game']}**", "inline": False},
                        {"name": "📊 Pick", "value": f"**{pick['pick']}**", "inline": True},
                        {"name": "💰 Odds", "value": pick['odds'], "inline": True},
                        {"name": "🎲 Units", "value": f"{pick['units']} unit{'s' if pick['units'] != '1' else ''}", "inline": True}
                    ],
                    "footer": {"text": "Bruce Marshall • SportsLine"},
                    "timestamp": datetime.now().isoformat()
                }
                
                payload = {"username": "SportsLine Monitor", "embeds": [embed]}
                
                r = requests.post(self.webhook, json=payload)
                r.raise_for_status()
                
                print(f"✅ Sent to Discord: {pick['game']}")
                self.seen_picks.add(pick_id)
                time.sleep(2)
                
            except Exception as e:
                print(f"Discord error: {e}")
    
    def run(self):
        print("="*50)
        print(f"SportsLine Monitor - {datetime.now().strftime('%I:%M %p')}")
        print("="*50)
        
        if not all([self.email, self.password, self.webhook]):
            print("❌ Missing credentials!")
            return
        
        if not self.login():
            print("❌ Login failed")
            return
        
        picks = self.extract_picks()
        
        if not picks:
            print("No picks found")
            return
        
        # Filter new picks
        new_picks = []
        for pick in picks:
            pick_id = self.generate_pick_id(pick)
            if pick_id not in self.seen_picks:
                new_picks.append(pick)
        
        if new_picks:
            print(f"\n📤 Sending {len(new_picks)} new picks...")
            self.send_to_discord(new_picks)
        else:
            print("No new picks to send")
        
        self.save_seen_picks()
        print("\n✅ Complete")

if __name__ == "__main__":
    monitor = SportsLineMonitor()
    monitor.run()