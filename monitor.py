#!/usr/bin/env python3
"""
SportsLine Monitor - FULL PAGE SEARCH VERSION
Searches the entire page for picks, not just the beginning
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
                json.dump(list(self.seen_picks)[-500:], f)
        except:
            pass
    
    def login(self):
        """Login to SportsLine"""
        try:
            print("Logging in...")
            
            # Get login page
            login_page = self.session.get(self.login_url)
            soup = BeautifulSoup(login_page.content, 'html.parser')
            
            # Build login data
            data = {
                'email': self.email,
                'password': self.password,
                'remember': '1',
                'remember_me': '1'
            }
            
            # Add hidden form fields
            form = soup.find('form')
            if form:
                for inp in form.find_all('input'):
                    name = inp.get('name')
                    if name and name not in data:
                        data[name] = inp.get('value', '')
            
            # Submit login
            response = self.session.post(self.login_url, data=data, allow_redirects=True)
            
            # Check if logged in
            if 'logout' in response.text.lower():
                print("✅ Login successful!")
                return True
            else:
                print("⚠️ Login may have failed, continuing anyway...")
                return True
                
        except Exception as e:
            print(f"Login error: {e}")
            return False
    
    def get_picks_from_page(self):
        """Get ALL picks from the ENTIRE page"""
        try:
            print("Fetching picks page...")
            r = self.session.get(self.expert_url)
            print(f"Page status: {r.status_code}")
            print(f"Page size: {len(r.content)} bytes")
            
            soup = BeautifulSoup(r.content, 'html.parser')
            
            # Get ALL text from the page
            full_text = soup.get_text()
            # Clean up whitespace
            full_text = ' '.join(full_text.split())
            
            print(f"Searching ENTIRE page text ({len(full_text)} characters)...")
            
            picks = []
            
            # Method 1: Find all game patterns in the ENTIRE text
            print("Looking for game patterns throughout the entire page...")
            
            # Multiple patterns to catch different formats
            patterns = [
                # Team @ Team (most common)
                r'([A-Z][A-Za-z\.\s]{2,25}?)\s*@\s*([A-Z][A-Za-z\.\s]{2,25})',
                # Team vs Team
                r'([A-Z][A-Za-z\.\s]{2,25}?)\s+vs\.?\s+([A-Z][A-Za-z\.\s]{2,25})',
                # Team at Team
                r'([A-Z][A-Za-z\.\s]{2,25}?)\s+at\s+([A-Z][A-Za-z\.\s]{2,25})',
                # With periods (L.A. Rams @ Seattle)
                r'([A-Z]\.?[A-Z]?\.?\s*[A-Za-z\s]{2,20}?)\s*@\s*([A-Z][A-Za-z\.\s]{2,25})'
            ]
            
            all_matches = []
            for pattern in patterns:
                matches = list(re.finditer(pattern, full_text))
                print(f"  Pattern found {len(matches)} potential games")
                all_matches.extend(matches)
            
            # Process each match found ANYWHERE in the page
            seen_games = set()
            checked_count = 0
            
            for match in all_matches:
                checked_count += 1
                team1 = match.group(1).strip()
                team2 = match.group(2).strip()
                
                # Clean team names
                team1 = re.sub(r'\s+', ' ', team1).strip()
                team2 = re.sub(r'\s+', ' ', team2).strip()
                
                # Remove obvious junk from team names
                junk_in_teams = ['UTC', 'Money Line', 'Point Spread', 'Over', 'Under', 'Subscri', 
                                'LAST', 'Total', 'Spread']
                for junk in junk_in_teams:
                    team1 = team1.replace(junk, '').strip()
                    team2 = team2.replace(junk, '').strip()
                
                # Basic validation
                if len(team1) < 3 or len(team2) < 3:
                    continue
                if len(team1) > 30 or len(team2) > 30:
                    continue
                    
                # Skip obvious non-teams
                skip_words = ['sportsline', 'cbs', 'copyright', 'privacy', 'terms', 'cookie',
                             'subscribe', 'login', 'password', 'email', 'footer', 'header',
                             'navigation', 'menu', 'search', 'share', 'follow', 'interactive']
                if any(skip in team1.lower() or skip in team2.lower() for skip in skip_words):
                    continue
                
                game = f"{team1} @ {team2}"
                
                # Skip duplicates
                if game in seen_games:
                    continue
                seen_games.add(game)
                
                # Get context (more context = better)
                start = max(0, match.start() - 500)
                end = min(len(full_text), match.end() + 500)
                context = full_text[start:end]
                
                # Look for pick indicators in the context
                pick_indicators = ['pick', 'play', 'bet', 'like', 'take', 'best bet', 'unit', 
                                  'confidence', 'lean', 'side', 'total', 'over', 'under',
                                  'spread', 'moneyline', 'money line']
                
                has_indicator = any(ind in context.lower() for ind in pick_indicators)
                
                if not has_indicator:
                    continue
                
                # This looks like a real pick!
                print(f"Found potential pick: {game}")
                
                # Extract details
                pick = self.extract_pick_details(game, context)
                if pick:
                    picks.append(pick)
            
            print(f"Checked {checked_count} potential games, found {len(picks)} valid picks")
            
            # Method 2: Also check structured elements
            # Look for divs/sections that might contain picks
            pick_containers = soup.find_all(['div', 'article', 'section', 'tr'])
            
            for container in pick_containers:
                text = container.get_text()
                # Quick check if this could be a pick
                if '@' in text or ' vs ' in text.lower() or ' at ' in text.lower():
                    if any(word in text.lower() for word in ['pick', 'play', 'bet', 'unit']):
                        # Try to extract a pick from this container
                        container_pick = self.extract_pick_from_container(container)
                        if container_pick:
                            # Check if we already have this game
                            if not any(p['game'] == container_pick['game'] for p in picks):
                                picks.append(container_pick)
                                print(f"Found pick in container: {container_pick['game']}")
            
            # Remove any remaining duplicates and validate
            final_picks = []
            seen_games_final = set()
            
            for pick in picks:
                # Clean the game string once more
                pick['game'] = self.clean_game_string(pick['game'])
                
                # Clean the pick string
                pick['pick'] = self.clean_pick_string(pick['pick'])
                
                # Validate it's a real pick
                if not self.is_valid_pick(pick):
                    continue
                
                # Check for duplicates
                if pick['game'] not in seen_games_final:
                    seen_games_final.add(pick['game'])
                    final_picks.append(pick)
                    print(f"✓ Final pick: {pick['game']} - {pick['pick']}")
            
            return final_picks
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def clean_pick_string(self, pick_str):
        """Clean up the pick string"""
        # Remove junk that got concatenated
        junk = ['Money Line', 'Point Spread', 'Over', 'Under', 'Subscri', 'LAST', 'Total']
        for j in junk:
            pick_str = pick_str.replace(j, '')
        
        # Remove huge numbers that are clearly wrong
        pick_str = re.sub(r'\+\d{4,}', '', pick_str)
        
        # Clean whitespace
        pick_str = ' '.join(pick_str.split())
        
        return pick_str.strip()
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def extract_pick_details(self, game, context):
        """Extract pick details from context - CLEANED UP"""
        try:
            # Clean the game string first
            game = self.clean_game_string(game)
            
            teams = game.split('@')
            if len(teams) != 2:
                return None
            
            away_team = teams[0].strip()
            home_team = teams[1].strip()
            
            # Default pick is home team
            pick_team = home_team
            
            # Try to find the actual pick
            pick_patterns = [
                rf'(?:pick|play|take|bet on?)\s+({re.escape(away_team)}|{re.escape(home_team)})',
                rf'({re.escape(away_team)}|{re.escape(home_team)})\s+[+-]\d+',
                rf'like\s+({re.escape(away_team)}|{re.escape(home_team)})'
            ]
            
            for pattern in pick_patterns:
                match = re.search(pattern, context, re.I)
                if match:
                    pick_team = match.group(1)
                    break
            
            # Look for spread
            spread = ""
            spread_match = re.search(r'([+-]\d+\.?\d?)(?:\s|$)', context)
            if spread_match:
                spread_val = spread_match.group(1)
                # Validate it's a reasonable spread
                try:
                    if -50 < float(spread_val) < 50:  # Reasonable spread range
                        spread = spread_val
                        pick_team = f"{pick_team} {spread}"
                except:
                    pass
            
            # Look for odds (should be 3-4 digits with +/-)
            odds = "N/A"
            odds_match = re.search(r'([+-]\d{3,4})(?!\d)', context)
            if odds_match:
                odds_val = odds_match.group(1)
                try:
                    if -5000 < int(odds_val) < 5000:  # Reasonable odds range
                        odds = odds_val
                except:
                    pass
            
            # Look for units
            units = "1"
            units_match = re.search(r'(\d+\.?\d?)\s*units?', context, re.I)
            if units_match:
                units_val = units_match.group(1)
                try:
                    if 0 < float(units_val) <= 10:  # Reasonable units range
                        units = units_val
                except:
                    pass
            
            # Look for confidence
            confidence = ""
            if any(term in context.lower() for term in ['best bet', '5 star', 'five star']):
                confidence = "⭐⭐⭐⭐⭐"
            elif '4 star' in context.lower():
                confidence = "⭐⭐⭐⭐"
            elif '3 star' in context.lower():
                confidence = "⭐⭐⭐"
            
            return {
                'game': game,
                'pick': pick_team,
                'odds': odds,
                'units': units,
                'confidence': confidence
            }
            
        except Exception as e:
            print(f"Error extracting details: {e}")
            return None
    
    def clean_game_string(self, game):
        """Clean up the game string by removing junk"""
        # Remove common junk patterns
        junk_patterns = [
            r'UTC',  # Timezone indicator
            r'Money Line.*',  # Bet type that got concatenated
            r'Point Spread.*',  # Bet type
            r'Over.*',  # Bet type
            r'Under.*',  # Bet type
            r'Subscri.*',  # "Subscribe" text
            r'LAST.*',  # Other junk
            r'\+\d{4,}.*',  # Weird long numbers
        ]
        
        for pattern in junk_patterns:
            game = re.sub(pattern, '', game, flags=re.I)
        
        # Clean extra whitespace
        game = ' '.join(game.split())
        
        # Ensure @ is properly spaced
        game = re.sub(r'\s*@\s*', ' @ ', game)
        
        return game.strip()
    
    def is_valid_pick(self, pick):
        """Validate that this is a real sports pick - IMPROVED"""
        if not pick or not pick.get('game'):
            return False
        
        game = pick['game']
        
        # Skip obvious junk
        if 'sportsline' in game.lower() or 'cbs' in game.lower():
            return False
        
        # Must have @ separator
        if '@' not in game:
            return False
        
        teams = game.split('@')
        if len(teams) != 2:
            return False
        
        # Both teams must be reasonable length
        for team in teams:
            team = team.strip()
            if len(team) < 3 or len(team) > 35:
                return False
        
        return True
    
    def extract_pick_from_container(self, container):
        """Extract pick from a specific HTML container"""
        try:
            text = container.get_text()
            text = ' '.join(text.split())  # Clean whitespace
            
            # Look for game
            match = re.search(r'([A-Z][A-Za-z\.\s]{2,25}?)\s*@\s*([A-Z][A-Za-z\.\s]{2,25})', text)
            if not match:
                match = re.search(r'([A-Z][A-Za-z\.\s]{2,25}?)\s+vs\.?\s+([A-Z][A-Za-z\.\s]{2,25})', text)
            
            if not match:
                return None
            
            game = f"{match.group(1).strip()} @ {match.group(2).strip()}"
            
            # Extract other details
            return self.extract_pick_details(game, text)
            
        except:
            return None
    
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
                
                # Build embed
                embed = {
                    "title": "🎯 New Bruce Marshall Pick",
                    "color": 0x00ff00 if not pick['confidence'] else 0xffd700,
                    "fields": [
                        {"name": "🏟️ Game", "value": f"**{pick['game']}**", "inline": False},
                        {"name": "📊 Pick", "value": f"**{pick['pick']}**", "inline": True},
                        {"name": "💰 Odds", "value": pick['odds'], "inline": True},
                        {"name": "🎲 Units", "value": f"{pick['units']} unit{'s' if pick['units'] != '1' else ''}", "inline": True}
                    ],
                    "footer": {"text": "Bruce Marshall • SportsLine"},
                    "timestamp": datetime.now().isoformat()
                }
                
                if pick['confidence']:
                    embed["fields"].insert(1, {"name": "🔥 Confidence", "value": pick['confidence'], "inline": False})
                
                payload = {"username": "SportsLine Monitor", "embeds": [embed]}
                
                r = requests.post(self.webhook, json=payload)
                r.raise_for_status()
                
                print(f"✅ Sent to Discord: {pick['game']}")
                self.seen_picks.add(pick_id)
                time.sleep(2)
                
            except Exception as e:
                print(f"Discord error: {e}")
    
    def run(self):
        """Main execution"""
        print("="*50)
        print(f"SportsLine Monitor - {datetime.now().strftime('%I:%M %p')}")
        print("="*50)
        
        if not all([self.email, self.password, self.webhook]):
            print("❌ Missing credentials!")
            return
        
        if not self.login():
            print("❌ Login failed")
            return
        
        picks = self.get_picks_from_page()
        
        if not picks:
            print("No picks found on page")
            print("\nPossible reasons:")
            print("1. No picks posted yet today")
            print("2. Picks are in a different format")
            print("3. Need to scroll or click to load picks")
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
            print("No new picks (all previously sent)")
        
        self.save_seen_picks()
        print("\n✅ Complete")

if __name__ == "__main__":
    monitor = SportsLineMonitor()
    monitor.run()