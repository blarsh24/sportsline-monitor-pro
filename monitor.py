#!/usr/bin/env python3
# testing
"""
SportsLine Monitor Pro v4.0
- Midnight: Send all LIVE picks (not yet played)
- Hourly: Check for NEW picks added since last check
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import time
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
import re
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Pick:
    """Represents a betting pick"""
    def __init__(self, game: str, pick: str, odds: str = "N/A", units: str = "1 unit", 
                 analysis: str = "", confidence: str = "", sport: str = "", status: str = "LIVE"):
        self.game = game
        self.pick = pick
        self.odds = odds
        self.units = units
        self.analysis = analysis[:500] if analysis else "Check SportsLine for details"
        self.confidence = confidence
        self.sport = sport
        self.status = status  # LIVE, WIN, LOSS, PUSH
        self.timestamp = datetime.now().isoformat()
        self.id = self._generate_id()
    
    def _generate_id(self) -> str:
        """Generate unique ID for this pick"""
        content = f"{self.game}-{self.pick}-{datetime.now().strftime('%Y-%m-%d')}"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def is_live(self) -> bool:
        """Check if pick is still live (not settled)"""
        return self.status.upper() == "LIVE"
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'game': self.game,
            'pick': self.pick,
            'odds': self.odds,
            'units': self.units,
            'analysis': self.analysis,
            'confidence': self.confidence,
            'sport': self.sport,
            'status': self.status,
            'timestamp': self.timestamp
        }

class SportsLineMonitor:
    """Main monitor class with midnight LIVE picks and hourly NEW picks"""
    
    def __init__(self):
        # Configuration
        self.base_url = "https://www.sportsline.com"
        self.expert_url = "https://www.sportsline.com/experts/51297150/bruce-marshall/"
        self.login_url = "https://www.sportsline.com/login"
        
        # Credentials from environment
        self.email = os.environ.get('SPORTSLINE_EMAIL')
        self.password = os.environ.get('SPORTSLINE_PASSWORD')
        self.webhook = os.environ.get('DISCORD_WEBHOOK_URL')
        
        # Check if this is a midnight run
        current_hour = datetime.now().hour
        self.is_midnight_run = (current_hour == 0) or os.environ.get('FORCE_MIDNIGHT', 'false').lower() == 'true'
        
        # Session management
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        
        # State management
        self.state_file = 'monitor_state.json'
        self.state = self.load_state()
        
        logger.info(f"✅ Monitor initialized - Mode: {'MIDNIGHT (All LIVE)' if self.is_midnight_run else 'HOURLY (New Only)'}")
    
    def verify_setup(self) -> bool:
        """Verify all requirements are met"""
        if not self.email or not self.password:
            logger.error("❌ Missing SportsLine credentials")
            return False
        if not self.webhook:
            logger.error("❌ Missing Discord webhook URL")
            return False
        logger.info("✅ Setup verified")
        return True
    
    def load_state(self) -> dict:
        """Load previous state"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load state: {e}")
        
        return {
            'sent_today': [],  # Picks sent today (reset at midnight)
            'all_known_picks': [],  # All picks we've ever seen
            'last_midnight_run': None,
            'last_check': None,
            'total_picks_sent': 0
        }
    
    def save_state(self):
        """Save current state"""
        try:
            self.state['last_check'] = datetime.now().isoformat()
            if self.is_midnight_run:
                self.state['last_midnight_run'] = datetime.now().isoformat()
                # Reset daily tracking at midnight
                self.state['sent_today'] = []
            
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save state: {e}")
    
    def login(self) -> bool:
        """Login to SportsLine"""
        try:
            logger.info("🔐 Logging in to SportsLine...")
            
            # Get login page first (for any CSRF tokens)
            login_page = self.session.get(self.login_url)
            soup = BeautifulSoup(login_page.content, 'html.parser')
            
            # Prepare login data
            login_data = {
                'email': self.email,
                'password': self.password,
                'remember_me': '1'
            }
            
            # Look for any hidden form fields (CSRF tokens, etc)
            form = soup.find('form')
            if form:
                for hidden in form.find_all('input', type='hidden'):
                    name = hidden.get('name')
                    value = hidden.get('value', '')
                    if name:
                        login_data[name] = value
            
            # Submit login
            response = self.session.post(
                self.login_url,
                data=login_data,
                allow_redirects=True,
                timeout=15
            )
            
            # Check if login succeeded
            if response.status_code == 200:
                # Check for login indicators in response
                if 'logout' in response.text.lower() or 'my account' in response.text.lower():
                    logger.info("✅ Login successful!")
                    return True
                else:
                    # Try visiting expert page to verify
                    test_response = self.session.get(self.expert_url)
                    if 'subscribe' not in test_response.text.lower()[:1000]:
                        logger.info("✅ Login successful (verified)!")
                        return True
            
            logger.warning("⚠️ Login may have failed - will try to continue")
            return True  # Continue anyway
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False
    
    def fetch_picks_page(self) -> Optional[str]:
        """Fetch the picks page HTML"""
        try:
            logger.info("📥 Fetching picks page...")
            response = self.session.get(self.expert_url, timeout=15)
            response.raise_for_status()
            
            if len(response.content) < 1000:
                logger.warning("Page seems too small")
                return None
            
            logger.info(f"✅ Fetched {len(response.content)} bytes")
            return response.text
            
        except Exception as e:
            logger.error(f"Error fetching page: {e}")
            return None
    
    def extract_picks(self, html: str) -> List[Pick]:
        """Extract picks from HTML"""
        picks = []
        soup = BeautifulSoup(html, 'html.parser')
        
        logger.info("🔍 Extracting picks...")
        
        # Strategy 1: Look for pick containers/cards
        pick_elements = soup.find_all(['div', 'article', 'section'], 
                                     class_=re.compile('pick|play|prediction|bet|selection', re.I))
        
        for element in pick_elements[:20]:  # Check more elements
            pick = self._parse_pick_element(element)
            if pick:
                picks.append(pick)
        
        # Strategy 2: Look for game matchups in text
        if len(picks) < 10:  # Get more picks
            text_picks = self._extract_from_text(soup.get_text())
            picks.extend(text_picks)
        
        # Remove duplicates
        unique_picks = []
        seen_ids = set()
        for pick in picks:
            if pick.id not in seen_ids:
                seen_ids.add(pick.id)
                unique_picks.append(pick)
        
        logger.info(f"✅ Found {len(unique_picks)} total picks")
        return unique_picks
    
    def _parse_pick_element(self, element) -> Optional[Pick]:
        """Parse a single pick element"""
        try:
            text = element.get_text()
            
            # Check for WIN/LOSS/PUSH status
            status = "LIVE"
            if re.search(r'\bWIN\b|\bWON\b|✅|💚', text, re.I):
                status = "WIN"
            elif re.search(r'\bLOSS\b|\bLOST\b|❌|🔴', text, re.I):
                status = "LOSS"
            elif re.search(r'\bPUSH\b', text, re.I):
                status = "PUSH"
            
            # Look for team matchup patterns
            # Pattern 1: Team @ Team
            match = re.search(r'([A-Z][\w\s\.\-]{2,30})\s*@\s*([A-Z][\w\s\.\-]{2,30})', text)
            if not match:
                # Pattern 2: Team vs Team
                match = re.search(r'([A-Z][\w\s\.\-]{2,30})\s+vs\.?\s+([A-Z][\w\s\.\-]{2,30})', text, re.I)
            
            if not match:
                return None
            
            away_team = match.group(1).strip()
            home_team = match.group(2).strip()
            game = f"{away_team} @ {home_team}"
            
            # Extract the pick
            pick_pattern = r'(?:Play|Pick|Take|Bet)\s+([A-Z][\w\s\.\-]+?)(?:\s+[+-]|\s+at|\.|,|$)'
            pick_match = re.search(pick_pattern, text, re.I)
            
            if pick_match:
                pick_team = pick_match.group(1).strip()
            else:
                # Default to home team if no clear pick
                pick_team = home_team
            
            # Extract spread if available
            spread_match = re.search(r'([+-]\d+\.?\d?)', text)
            if spread_match:
                pick_team = f"{pick_team} {spread_match.group(1)}"
            
            # Extract odds
            odds_match = re.search(r'([+-]\d{3,4})(?!\d)', text)
            odds = odds_match.group(1) if odds_match else "Check Site"
            
            # Extract units
            units_match = re.search(r'(\d+\.?\d?)\s*units?', text, re.I)
            units = f"{units_match.group(1)} units" if units_match else "1 unit"
            
            # Detect confidence level
            confidence = self._detect_confidence(text)
            
            # Detect sport
            sport = self._detect_sport(game)
            
            # Clean analysis
            analysis = self._extract_analysis(element)
            
            return Pick(
                game=game,
                pick=pick_team,
                odds=odds,
                units=units,
                analysis=analysis,
                confidence=confidence,
                sport=sport,
                status=status
            )
            
        except Exception as e:
            logger.debug(f"Could not parse element: {e}")
            return None
    
    def _extract_from_text(self, text: str) -> List[Pick]:
        """Fallback text extraction"""
        picks = []
        
        # Find all potential matchups
        pattern = r'([A-Z][\w\s\.\-]{2,25})\s*@\s*([A-Z][\w\s\.\-]{2,25})'
        
        for match in re.finditer(pattern, text):
            away = match.group(1).strip()
            home = match.group(2).strip()
            
            # Skip if contains junk
            if any(word in away.lower() or word in home.lower() 
                   for word in ['subscribe', 'copyright', 'privacy', 'terms']):
                continue
            
            game = f"{away} @ {home}"
            
            # Get context around match
            start = max(0, match.start() - 300)
            end = min(len(text), match.end() + 400)
            context = text[start:end]
            
            # Check status
            status = "LIVE"
            if re.search(r'\bWIN\b|\bWON\b', context, re.I):
                status = "WIN"
            elif re.search(r'\bLOSS\b|\bLOST\b', context, re.I):
                status = "LOSS"
            
            # Look for pick indicators
            if re.search(r'(play|pick|take|bet|like)', context, re.I):
                picks.append(Pick(
                    game=game,
                    pick=home,  # Default
                    odds="See Site",
                    units="1 unit",
                    analysis=context[:200].strip(),
                    sport=self._detect_sport(game),
                    status=status
                ))
                
                if len(picks) >= 10:
                    break
        
        return picks
    
    def _detect_confidence(self, text: str) -> str:
        """Detect confidence level from text"""
        text_lower = text.lower()
        if 'best bet' in text_lower or '5 star' in text_lower or 'five star' in text_lower:
            return "⭐⭐⭐⭐⭐ BEST BET"
        elif '4 star' in text_lower or 'four star' in text_lower:
            return "⭐⭐⭐⭐ Strong Play"
        elif '3 star' in text_lower:
            return "⭐⭐⭐ Good Value"
        elif 'lock' in text_lower:
            return "🔒 LOCK"
        return "Standard Play"
    
    def _detect_sport(self, game: str) -> str:
        """Detect sport from team names"""
        game_lower = game.lower()
        
        # NFL teams
        nfl = ['patriots', 'bills', 'dolphins', 'jets', 'ravens', 'bengals', 'browns', 'steelers',
               'texans', 'colts', 'jaguars', 'titans', 'broncos', 'chiefs', 'raiders', 'chargers',
               'cowboys', 'giants', 'eagles', 'commanders', 'bears', 'lions', 'packers', 'vikings',
               'falcons', 'panthers', 'saints', 'buccaneers', '49ers', 'cardinals', 'rams', 'seahawks']
        
        # NBA teams
        nba = ['celtics', 'nets', 'knicks', '76ers', 'raptors', 'bulls', 'cavaliers', 'pistons',
               'pacers', 'bucks', 'hawks', 'hornets', 'heat', 'magic', 'wizards', 'nuggets',
               'timberwolves', 'thunder', 'blazers', 'jazz', 'warriors', 'clippers', 'lakers',
               'suns', 'kings', 'mavericks', 'rockets', 'grizzlies', 'pelicans', 'spurs']
        
        # MLB teams
        mlb = ['orioles', 'red sox', 'yankees', 'rays', 'blue jays', 'white sox', 'guardians',
               'tigers', 'royals', 'twins', 'astros', 'angels', 'athletics', 'mariners', 'rangers',
               'braves', 'marlins', 'mets', 'phillies', 'nationals', 'brewers', 'cubs', 'reds',
               'pirates', 'cardinals', 'diamondbacks', 'rockies', 'dodgers', 'padres', 'giants']
        
        if any(team in game_lower for team in nfl):
            return "🏈 NFL"
        elif any(team in game_lower for team in nba):
            return "🏀 NBA"
        elif any(team in game_lower for team in mlb):
            return "⚾ MLB"
        elif 'state' in game_lower or 'university' in game_lower:
            return "🎓 College"
        else:
            return "🏟️ Sports"
    
    def _extract_analysis(self, element) -> str:
        """Extract clean analysis text"""
        try:
            text = element.get_text()
            
            # Remove common junk patterns
            junk = [
                r'Subscribe.*?(?:\.|$)',
                r'Join.*?(?:\.|$)',
                r'Sign up.*?(?:\.|$)',
                r'©.*?(?:\.|$)',
                r'All rights reserved.*?(?:\.|$)'
            ]
            
            for pattern in junk:
                text = re.sub(pattern, '', text, flags=re.I)
            
            # Clean whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Extract relevant part
            if 'analysis' in text.lower():
                match = re.search(r'analysis[:\s]+(.{50,300})', text, re.I)
                if match:
                    return match.group(1)
            
            # Return first 200 chars as fallback
            return text[:200] if len(text) > 50 else "Expert pick - check site for analysis"
            
        except Exception:
            return "Check SportsLine for full analysis"
    
    def process_picks(self, all_picks: List[Pick]) -> List[Pick]:
        """Process picks based on run type (midnight vs hourly)"""
        picks_to_send = []
        
        if self.is_midnight_run:
            # MIDNIGHT: Send ALL LIVE picks (not WIN/LOSS/PUSH)
            logger.info("🌙 MIDNIGHT RUN - Sending all LIVE picks")
            
            for pick in all_picks:
                if pick.is_live():
                    picks_to_send.append(pick)
                    # Track that we sent this today
                    if pick.id not in self.state['sent_today']:
                        self.state['sent_today'].append(pick.id)
            
            logger.info(f"Found {len(picks_to_send)} LIVE picks to send")
            
        else:
            # HOURLY: Send only NEW picks not seen before
            logger.info("⏰ HOURLY RUN - Checking for NEW picks only")
            
            known_picks = set(self.state.get('all_known_picks', []))
            sent_today = set(self.state.get('sent_today', []))
            
            for pick in all_picks:
                if pick.id not in known_picks:
                    # This is a brand new pick we've never seen
                    picks_to_send.append(pick)
                    known_picks.add(pick.id)
                    sent_today.add(pick.id)
                    logger.info(f"NEW PICK: {pick.game} - {pick.pick}")
            
            # Update state
            self.state['all_known_picks'] = list(known_picks)[-200:]  # Keep last 200
            self.state['sent_today'] = list(sent_today)
            
            logger.info(f"Found {len(picks_to_send)} NEW picks to send")
        
        return picks_to_send
    
    def send_to_discord(self, picks: List[Pick], is_midnight: bool = False):
        """Send picks to Discord"""
        if not picks:
            logger.info("No picks to send")
            return
        
        # Send header message for midnight run
        if is_midnight:
            self.send_midnight_header(len(picks))
        
        for pick in picks:
            try:
                # Determine embed color based on confidence
                color = 0x00FF00  # Green default
                if "BEST BET" in pick.confidence or "⭐⭐⭐⭐⭐" in pick.confidence:
                    color = 0xFFD700  # Gold
                elif "LOCK" in pick.confidence:
                    color = 0xFF0000  # Red
                elif "⭐⭐⭐⭐" in pick.confidence:
                    color = 0xFFA500  # Orange
                
                # Adjust title based on run type
                title = "🌙 LIVE Pick (Midnight Update)" if is_midnight else "🆕 NEW Bruce Marshall Pick"
                
                embed = {
                    "title": title,
                    "color": color,
                    "fields": [
                        {"name": f"{pick.sport} Game", "value": pick.game, "inline": False},
                        {"name": "📊 Pick", "value": f"**{pick.pick}**", "inline": True},
                        {"name": "💰 Odds", "value": pick.odds, "inline": True},
                        {"name": "🎲 Units", "value": pick.units, "inline": True},
                    ],
                    "footer": {"text": f"SportsLine Premium • Status: {pick.status}"},
                    "timestamp": pick.timestamp
                }
                
                # Add confidence if not standard
                if pick.confidence != "Standard Play":
                    embed["fields"].insert(1, {
                        "name": "🔥 Confidence",
                        "value": f"**{pick.confidence}**",
                        "inline": False
                    })
                
                # Add analysis
                if len(pick.analysis) > 20:
                    embed["fields"].append({
                        "name": "📝 Analysis",
                        "value": pick.analysis[:500],
                        "inline": False
                    })
                
                # Add link
                embed["fields"].append({
                    "name": "🔗 Full Details",
                    "value": f"[View on SportsLine]({self.expert_url})",
                    "inline": False
                })
                
                payload = {
                    "username": "Bruce Marshall Monitor",
                    "avatar_url": "https://www.sportsline.com/images/experts/51297150.jpg",
                    "embeds": [embed]
                }
                
                response = requests.post(self.webhook, json=payload, timeout=10)
                response.raise_for_status()
                
                logger.info(f"✅ Sent: {pick.game} - {pick.pick} [{pick.status}]")
                time.sleep(2)  # Rate limit
                
            except Exception as e:
                logger.error(f"Discord error for {pick.game}: {e}")
    
    def send_midnight_header(self, count: int):
        """Send header message for midnight run"""
        try:
            embed = {
                "title": "🌙 Daily LIVE Picks Summary",
                "description": f"All currently LIVE picks from Bruce Marshall",
                "color": 0x0099FF,
                "fields": [
                    {"name": "📊 Total LIVE Picks", "value": str(count), "inline": True},
                    {"name": "⏰ Time", "value": datetime.now().strftime('%I:%M %p'), "inline": True},
                ],
                "footer": {"text": "All picks below are still pending (not settled)"}
            }
            
            payload = {
                "username": "Daily Summary",
                "embeds": [embed]
            }
            
            requests.post(self.webhook, json=payload, timeout=10)
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"Could not send header: {e}")
    
    def run(self):
        """Main execution"""
        logger.info("="*50)
        logger.info(f"🚀 SportsLine Monitor - {datetime.now().strftime('%I:%M %p')}")
        logger.info(f"Mode: {'MIDNIGHT (All LIVE)' if self.is_midnight_run else 'HOURLY (New Only)'}")
        
        # Verify setup
        if not self.verify_setup():
            return
        
        # Login
        if not self.login():
            logger.error("Failed to login")
            return
        
        # Fetch page
        html = self.fetch_picks_page()
        if not html:
            logger.error("Failed to fetch picks page")
            return
        
        # Extract all picks
        all_picks = self.extract_picks(html)
        logger.info(f"Total picks found on page: {len(all_picks)}")
        
        # Show status breakdown
        live_count = sum(1 for p in all_picks if p.is_live())
        win_count = sum(1 for p in all_picks if p.status == "WIN")
        loss_count = sum(1 for p in all_picks if p.status == "LOSS")
        logger.info(f"Status: {live_count} LIVE, {win_count} WIN, {loss_count} LOSS")
        
        # Process based on run type
        picks_to_send = self.process_picks(all_picks)
        
        # Send to Discord
        if picks_to_send:
            logger.info(f"📤 Sending {len(picks_to_send)} picks to Discord...")
            self.send_to_discord(picks_to_send, is_midnight=self.is_midnight_run)
            self.state['total_picks_sent'] = self.state.get('total_picks_sent', 0) + len(picks_to_send)
        else:
            logger.info("✅ No picks to send")
        
        # Save state
        self.save_state()
        
        logger.info(f"✅ Check complete - Total sent all-time: {self.state.get('total_picks_sent', 0)}")
        logger.info("="*50)

def main():
    try:
        monitor = SportsLineMonitor()
        monitor.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        # Send error notification
        webhook = os.environ.get('DISCORD_WEBHOOK_URL')
        if webhook:
            requests.post(webhook, json={
                "content": f"⚠️ Monitor error: {str(e)[:100]}"
            })

if __name__ == "__main__":
    main()