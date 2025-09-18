#!/usr/bin/env python3
"""
SportsLine Monitor Pro v5.0 - FINAL PRODUCTION VERSION
Perfect Discord formatting and status tracking
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
    """Represents a betting pick with clean data"""
    def __init__(self, game: str, pick: str, odds: str = "N/A", units: str = "1 unit", 
                 analysis: str = "", confidence: str = "", sport: str = "", status: str = "LIVE"):
        # Clean the game string - remove any garbage
        self.game = self._clean_game_string(game)
        # Clean the pick - remove duplicates and garbage
        self.pick = self._clean_pick_string(pick)
        self.odds = odds if odds != "See Site" else "Check Site"
        self.units = units
        # Clean analysis - remove unrelated text
        self.analysis = self._clean_analysis(analysis)
        self.confidence = confidence
        self.sport = sport
        self.status = status.upper()  # LIVE, WON, LOST, PUSH
        self.timestamp = datetime.now().isoformat()
        self.id = self._generate_id()
    
    def _clean_game_string(self, game: str) -> str:
        """Clean up game matchup string"""
        # Remove UTC, numbers, and weird characters
        game = re.sub(r'UTC.*', '', game)
        game = re.sub(r'\d{1,2}(?!\d)', '', game)  # Remove single/double digits
        game = re.sub(r'[^\w\s@\.\-]', '', game)
        game = re.sub(r'\s+', ' ', game).strip()
        
        # Ensure proper @ formatting
        if '@' not in game and ' at ' in game.lower():
            game = game.replace(' at ', ' @ ')
        
        return game
    
    def _clean_pick_string(self, pick: str) -> str:
        """Clean up pick string - remove duplicates"""
        # Remove duplicate team names and clean
        pick = re.sub(r'(\w+)(\1)+', r'\1', pick)  # Remove duplicate words
        pick = re.sub(r'Money Line[A-Z]*', '', pick)  # Remove Money Line text
        pick = re.sub(r'[^\w\s\+\-\.]', '', pick)
        pick = re.sub(r'\s+', ' ', pick).strip()
        
        # Extract just team name and spread if present
        parts = pick.split()
        if parts:
            # Look for spread
            spread = None
            team_parts = []
            for part in parts:
                if re.match(r'^[+\-]\d+\.?\d*$', part):
                    spread = part
                else:
                    team_parts.append(part)
            
            team = ' '.join(team_parts[:3])  # Max 3 words for team name
            if spread:
                return f"{team} {spread}"
            return team
        
        return pick
    
    def _clean_analysis(self, analysis: str) -> str:
        """Clean analysis text - remove unrelated content"""
        if not analysis:
            return "Check SportsLine for full analysis"
        
        # Remove common junk patterns
        junk_patterns = [
            r'UTC.*',
            r'Money Line[A-Z]*',
            r'Join Now.*',
            r'Subscribe.*',
            r'©.*',
            r'San Siro.*',  # Random unrelated text
            r'Inter lineup.*',  # Random unrelated text
            r'Marcus Thuram.*'  # Random unrelated text
        ]
        
        for pattern in junk_patterns:
            analysis = re.sub(pattern, '', analysis, flags=re.I)
        
        # Clean whitespace
        analysis = re.sub(r'\s+', ' ', analysis).strip()
        
        # If analysis is too short or seems wrong, provide default
        if len(analysis) < 20 or 'calhanoglu' in analysis.lower():
            return "Bruce Marshall's expert pick - check SportsLine for full analysis"
        
        return analysis[:400]  # Limit length
    
    def _generate_id(self) -> str:
        """Generate unique ID for this pick"""
        content = f"{self.game}-{self.pick}-{datetime.now().strftime('%Y-%m-%d')}"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def is_live(self) -> bool:
        """Check if pick is still live (not settled)"""
        return self.status == "LIVE"
    
    def get_status_emoji(self) -> str:
        """Get emoji for status"""
        status_map = {
            "LIVE": "🔴",
            "WON": "✅", 
            "LOST": "❌",
            "PUSH": "➖"
        }
        return status_map.get(self.status, "⚪")
    
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
    """Main monitor with clean extraction and perfect Discord formatting"""
    
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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive'
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
            'sent_today': [],
            'all_known_picks': [],
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
                self.state['sent_today'] = []  # Reset daily
            
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save state: {e}")
    
    def login(self) -> bool:
        """Login to SportsLine"""
        try:
            logger.info("🔐 Logging in...")
            
            login_page = self.session.get(self.login_url)
            soup = BeautifulSoup(login_page.content, 'html.parser')
            
            login_data = {
                'email': self.email,
                'password': self.password,
                'remember_me': '1'
            }
            
            # Add hidden fields
            form = soup.find('form')
            if form:
                for hidden in form.find_all('input', type='hidden'):
                    name = hidden.get('name')
                    value = hidden.get('value', '')
                    if name:
                        login_data[name] = value
            
            response = self.session.post(
                self.login_url,
                data=login_data,
                allow_redirects=True,
                timeout=15
            )
            
            # Simple success check
            if 'logout' in response.text.lower() or len(response.text) > 10000:
                logger.info("✅ Login successful")
                return True
            
            logger.info("⚠️ Login uncertain, continuing...")
            return True
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False
    
    def fetch_picks_page(self) -> Optional[str]:
        """Fetch the picks page HTML"""
        try:
            logger.info("📥 Fetching picks...")
            response = self.session.get(self.expert_url, timeout=15)
            response.raise_for_status()
            
            if len(response.content) < 1000:
                logger.warning("Page too small")
                return None
            
            logger.info(f"✅ Fetched {len(response.content)} bytes")
            return response.text
            
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return None
    
    def extract_picks(self, html: str) -> List[Pick]:
        """Extract picks with clean data"""
        picks = []
        soup = BeautifulSoup(html, 'html.parser')
        
        logger.info("🔍 Extracting picks...")
        
        # Remove script and style elements first
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Get text and clean it
        text = soup.get_text()
        text = re.sub(r'\s+', ' ', text)
        
        # Find all game matchups (more specific pattern)
        # Pattern: Team @ Team or Team vs Team
        game_patterns = [
            r'([A-Z][A-Za-z\.\-\s]{2,20})\s*@\s*([A-Z][A-Za-z\.\-\s]{2,20})',
            r'([A-Z][A-Za-z\.\-\s]{2,20})\s+vs\.?\s+([A-Z][A-Za-z\.\-\s]{2,20})'
        ]
        
        all_matches = []
        for pattern in game_patterns:
            matches = list(re.finditer(pattern, text))
            all_matches.extend(matches)
        
        # Process each match
        for match in all_matches[:15]:  # Limit to prevent too many
            try:
                away = match.group(1).strip()
                home = match.group(2).strip()
                
                # Skip if teams too short or contain junk
                if len(away) < 3 or len(home) < 3:
                    continue
                if any(junk in away.lower() + home.lower() for junk in 
                       ['subscribe', 'copyright', 'utc', 'privacy', 'terms']):
                    continue
                
                game = f"{away} @ {home}"
                
                # Get context around the match
                start = max(0, match.start() - 300)
                end = min(len(text), match.end() + 500)
                context = text[start:end]
                
                # Detect status
                status = "LIVE"
                if re.search(r'\bWON?\b|✅|Winner', context, re.I):
                    status = "WON"
                elif re.search(r'\bLOST?\b|❌|Loser', context, re.I):
                    status = "LOST"
                elif re.search(r'\bPUSH\b|Tie', context, re.I):
                    status = "PUSH"
                
                # Find the actual pick
                pick_text = home  # Default
                pick_patterns = [
                    r'(?:Play|Pick|Take|Bet on)\s+([A-Z][A-Za-z\.\-\s]+?)(?:\s+[+\-\d]|\.|,|$)',
                    r'([A-Z][A-Za-z\.\-\s]+?)\s+([+\-]\d+\.?\d?)',
                ]
                
                for pp in pick_patterns:
                    pm = re.search(pp, context)
                    if pm:
                        pick_text = pm.group(1).strip()
                        if len(pm.groups()) > 1 and pm.group(2):
                            pick_text += f" {pm.group(2)}"
                        break
                
                # Extract odds
                odds_match = re.search(r'([+\-]\d{3,4})(?!\d)', context)
                odds = odds_match.group(1) if odds_match else "Check Site"
                
                # Extract units
                units_match = re.search(r'(\d+\.?\d?)\s*units?', context, re.I)
                units = f"{units_match.group(1)} units" if units_match else "1 unit"
                
                # Extract confidence
                confidence = self._detect_confidence(context)
                
                # Extract sport
                sport = self._detect_sport(game)
                
                # Extract analysis (clean)
                analysis = self._extract_clean_analysis(context, game)
                
                pick = Pick(
                    game=game,
                    pick=pick_text,
                    odds=odds,
                    units=units,
                    analysis=analysis,
                    confidence=confidence,
                    sport=sport,
                    status=status
                )
                
                picks.append(pick)
                logger.info(f"Found: {pick.game} → {pick.pick} [{pick.status}]")
                
            except Exception as e:
                logger.debug(f"Parse error: {e}")
                continue
        
        # Remove duplicates
        unique_picks = []
        seen_ids = set()
        for pick in picks:
            if pick.id not in seen_ids:
                seen_ids.add(pick.id)
                unique_picks.append(pick)
        
        logger.info(f"✅ Extracted {len(unique_picks)} unique picks")
        return unique_picks
    
    def _detect_confidence(self, text: str) -> str:
        """Detect confidence level"""
        text_lower = text.lower()
        if 'best bet' in text_lower or '5 star' in text_lower or 'five star' in text_lower:
            return "⭐⭐⭐⭐⭐ BEST BET"
        elif '4 star' in text_lower:
            return "⭐⭐⭐⭐ Strong"
        elif '3 star' in text_lower:
            return "⭐⭐⭐ Good"
        elif 'lock' in text_lower:
            return "🔒 LOCK"
        return ""
    
    def _detect_sport(self, game: str) -> str:
        """Detect sport from team names"""
        game_lower = game.lower()
        
        nfl_teams = ['patriots', 'bills', 'jets', 'dolphins', 'ravens', 'steelers', 'browns', 'bengals',
                     'chiefs', 'raiders', 'broncos', 'chargers', 'texans', 'colts', 'titans', 'jaguars',
                     'eagles', 'cowboys', 'giants', 'commanders', 'packers', 'bears', 'lions', 'vikings',
                     '49ers', 'seahawks', 'rams', 'cardinals', 'saints', 'falcons', 'panthers', 'buccaneers']
        
        nba_teams = ['celtics', 'nets', 'knicks', '76ers', 'sixers', 'raptors', 'bulls', 'cavaliers',
                     'pistons', 'pacers', 'bucks', 'hawks', 'hornets', 'heat', 'magic', 'wizards',
                     'nuggets', 'timberwolves', 'thunder', 'blazers', 'jazz', 'warriors', 'clippers',
                     'lakers', 'suns', 'kings', 'mavericks', 'rockets', 'grizzlies', 'pelicans', 'spurs']
        
        mlb_teams = ['orioles', 'yankees', 'red sox', 'rays', 'blue jays', 'white sox', 'guardians',
                     'tigers', 'royals', 'twins', 'astros', 'angels', 'athletics', 'mariners', 'rangers',
                     'braves', 'marlins', 'mets', 'phillies', 'nationals', 'brewers', 'cubs', 'reds',
                     'pirates', 'cardinals', 'diamondbacks', 'rockies', 'dodgers', 'padres', 'giants']
        
        if any(team in game_lower for team in nfl_teams):
            return "🏈 NFL"
        elif any(team in game_lower for team in nba_teams):
            return "🏀 NBA"
        elif any(team in game_lower for team in mlb_teams):
            return "⚾ MLB"
        elif 'college' in game_lower or 'state' in game_lower or 'university' in game_lower:
            return "🎓 NCAA"
        else:
            return "🏟️"
    
    def _extract_clean_analysis(self, context: str, game: str) -> str:
        """Extract only relevant analysis"""
        # Try to find actual analysis
        analysis_patterns = [
            r'(?:Analysis|Reasoning|Why)[:\s]+([^.]+\.)',
            r'(?:The|This|These)\s+(?:team|play|pick)[^.]+\.',
            r'[A-Z][^.]*(?:should|will|could|might)[^.]+\.'
        ]
        
        for pattern in analysis_patterns:
            match = re.search(pattern, context, re.I)
            if match:
                analysis = match.group(0) if match.group(0) else match.group(1)
                # Clean it
                analysis = re.sub(r'UTC.*', '', analysis)
                analysis = re.sub(r'Money Line.*', '', analysis)
                analysis = re.sub(r'\s+', ' ', analysis).strip()
                
                # Make sure it's related to the game
                if any(team in analysis for team in game.split('@')):
                    return analysis[:300]
        
        return "Bruce Marshall's expert pick - see full analysis on SportsLine"
    
    def process_picks(self, all_picks: List[Pick]) -> List[Pick]:
        """Process picks based on run type"""
        picks_to_send = []
        
        if self.is_midnight_run:
            # MIDNIGHT: Send ALL LIVE picks
            logger.info("🌙 MIDNIGHT RUN - Sending all LIVE picks")
            
            for pick in all_picks:
                if pick.is_live():
                    picks_to_send.append(pick)
                    if pick.id not in self.state['sent_today']:
                        self.state['sent_today'].append(pick.id)
            
            logger.info(f"Found {len(picks_to_send)} LIVE picks")
            
        else:
            # HOURLY: Send only NEW picks
            logger.info("⏰ HOURLY RUN - Checking for NEW picks")
            
            known_picks = set(self.state.get('all_known_picks', []))
            sent_today = set(self.state.get('sent_today', []))
            
            for pick in all_picks:
                if pick.id not in known_picks:
                    picks_to_send.append(pick)
                    known_picks.add(pick.id)
                    sent_today.add(pick.id)
                    logger.info(f"NEW: {pick.game}")
            
            self.state['all_known_picks'] = list(known_picks)[-200:]
            self.state['sent_today'] = list(sent_today)
            
            logger.info(f"Found {len(picks_to_send)} NEW picks")
        
        return picks_to_send
    
    def send_to_discord(self, picks: List[Pick], is_midnight: bool = False):
        """Send CLEAN Discord notifications"""
        if not picks:
            logger.info("No picks to send")
            return
        
        # Send header for midnight
        if is_midnight:
            self.send_midnight_header(len(picks))
        
        for pick in picks:
            try:
                # Color based on confidence
                color = 0x2ECC71  # Green default
                if "BEST BET" in pick.confidence or "⭐⭐⭐⭐⭐" in pick.confidence:
                    color = 0xFFD700  # Gold
                elif "LOCK" in pick.confidence:
                    color = 0xE74C3C  # Red
                elif "⭐⭐⭐⭐" in pick.confidence:
                    color = 0xF39C12  # Orange
                
                # Title based on run type
                if is_midnight:
                    title = f"🌙 LIVE Pick - Bruce Marshall"
                else:
                    title = f"🆕 NEW Pick - Bruce Marshall"
                
                # Build clean embed
                embed = {
                    "title": title,
                    "color": color,
                    "fields": [
                        {
                            "name": f"{pick.sport} Game",
                            "value": f"**{pick.game}**",
                            "inline": False
                        },
                        {
                            "name": "📊 Pick",
                            "value": f"**{pick.pick}**",
                            "inline": True
                        },
                        {
                            "name": "💰 Odds",
                            "value": pick.odds,
                            "inline": True
                        },
                        {
                            "name": "🎲 Units",
                            "value": pick.units,
                            "inline": True
                        }
                    ],
                    "timestamp": pick.timestamp
                }
                
                # Add status badge
                status_field = {
                    "name": "Status",
                    "value": f"{pick.get_status_emoji()} **{pick.status}**",
                    "inline": True
                }
                embed["fields"].insert(1, status_field)
                
                # Add confidence if present
                if pick.confidence:
                    embed["fields"].insert(2, {
                        "name": "🔥 Confidence",
                        "value": pick.confidence,
                        "inline": False
                    })
                
                # Add clean analysis
                if pick.analysis and len(pick.analysis) > 30:
                    embed["fields"].append({
                        "name": "📝 Analysis",
                        "value": pick.analysis,
                        "inline": False
                    })
                
                # Footer
                embed["footer"] = {
                    "text": f"Bruce Marshall • SportsLine Premium",
                    "icon_url": "https://www.sportsline.com/images/experts/51297150.jpg"
                }
                
                payload = {
                    "username": "SportsLine Monitor",
                    "avatar_url": "https://www.sportsline.com/images/experts/51297150.jpg",
                    "embeds": [embed]
                }
                
                response = requests.post(self.webhook, json=payload, timeout=10)
                response.raise_for_status()
                
                logger.info(f"✅ Sent: {pick.game}")
                time.sleep(2)  # Rate limit
                
            except Exception as e:
                logger.error(f"Discord error: {e}")
    
    def send_midnight_header(self, count: int):
        """Send clean midnight header"""
        try:
            embed = {
                "title": "🌙 Daily LIVE Picks Summary",
                "description": "All active picks from Bruce Marshall that haven't been settled yet",
                "color": 0x3498DB,
                "fields": [
                    {
                        "name": "📊 Total LIVE Picks",
                        "value": f"**{count}**",
                        "inline": True
                    },
                    {
                        "name": "⏰ Updated",
                        "value": datetime.now().strftime('%I:%M %p EST'),
                        "inline": True
                    }
                ],
                "footer": {
                    "text": "All picks below are pending (not yet settled)"
                }
            }
            
            payload = {
                "username": "SportsLine Monitor",
                "embeds": [embed]
            }
            
            requests.post(self.webhook, json=payload, timeout=10)
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"Header error: {e}")
    
    def run(self):
        """Main execution"""
        logger.info("="*50)
        logger.info(f"🚀 Starting - {datetime.now().strftime('%I:%M %p')}")
        logger.info(f"Mode: {'MIDNIGHT' if self.is_midnight_run else 'HOURLY'}")
        
        if not self.verify_setup():
            return
        
        if not self.login():
            logger.error("Login failed")
            return
        
        html = self.fetch_picks_page()
        if not html:
            logger.error("No page content")
            return
        
        all_picks = self.extract_picks(html)
        
        # Show breakdown
        live = sum(1 for p in all_picks if p.status == "LIVE")
        won = sum(1 for p in all_picks if p.status == "WON")
        lost = sum(1 for p in all_picks if p.status == "LOST")
        logger.info(f"Found: {live} LIVE, {won} WON, {lost} LOST")
        
        picks_to_send = self.process_picks(all_picks)
        
        if picks_to_send:
            logger.info(f"📤 Sending {len(picks_to_send)} picks...")
            self.send_to_discord(picks_to_send, is_midnight=self.is_midnight_run)
            self.state['total_picks_sent'] = self.state.get('total_picks_sent', 0) + len(picks_to_send)
        else:
            logger.info("✅ No picks to send")
        
        self.save_state()
        logger.info("✅ Complete")
        logger.info("="*50)

def main():
    try:
        monitor = SportsLineMonitor()
        monitor.run()
    except Exception as e:
        logger.error(f"Fatal: {e}")
        webhook = os.environ.get('DISCORD_WEBHOOK_URL')
        if webhook:
            requests.post(webhook, json={"content": f"⚠️ Error: {str(e)[:100]}"})

if __name__ == "__main__":
    main()