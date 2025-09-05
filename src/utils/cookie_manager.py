"""
Cookie management module for handling browser cookies
"""

import json
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class CookieManager:
    """Manages browser cookies for session persistence"""
    
    def __init__(self, cookie_file: Optional[str] = None):
        """
        Initialize cookie manager
        
        Args:
            cookie_file: Path to cookie storage file
        """
        self.cookie_file = Path(cookie_file) if cookie_file else Path.home() / '.curlwright' / 'cookies.pkl'
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        self.cookies: List[Dict[str, Any]] = []
    
    async def save_cookies(self, context) -> None:
        """
        Save cookies from browser context
        
        Args:
            context: Playwright browser context
        """
        try:
            self.cookies = await context.cookies()
            
            # Save to file
            with open(self.cookie_file, 'wb') as f:
                pickle.dump(self.cookies, f)
            
            logger.info(f"Saved {len(self.cookies)} cookies to {self.cookie_file}")
            
        except Exception as e:
            logger.error(f"Failed to save cookies: {e}")
    
    async def load_cookies(self, context) -> bool:
        """
        Load cookies into browser context
        
        Args:
            context: Playwright browser context
            
        Returns:
            True if cookies were loaded successfully
        """
        try:
            if not self.cookie_file.exists():
                logger.info("No cookie file found")
                return False
            
            with open(self.cookie_file, 'rb') as f:
                self.cookies = pickle.load(f)
            
            if self.cookies:
                await context.add_cookies(self.cookies)
                logger.info(f"Loaded {len(self.cookies)} cookies")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to load cookies: {e}")
            return False
    
    def clear_cookies(self) -> None:
        """Clear all stored cookies"""
        try:
            self.cookies = []
            if self.cookie_file.exists():
                self.cookie_file.unlink()
            logger.info("Cookies cleared")
            
        except Exception as e:
            logger.error(f"Failed to clear cookies: {e}")
    
    def export_cookies_json(self, output_file: str) -> None:
        """
        Export cookies to JSON format
        
        Args:
            output_file: Path to output JSON file
        """
        try:
            with open(output_file, 'w') as f:
                json.dump(self.cookies, f, indent=2)
            logger.info(f"Exported cookies to {output_file}")
            
        except Exception as e:
            logger.error(f"Failed to export cookies: {e}")
    
    def import_cookies_json(self, input_file: str) -> bool:
        """
        Import cookies from JSON file
        
        Args:
            input_file: Path to input JSON file
            
        Returns:
            True if import was successful
        """
        try:
            with open(input_file, 'r') as f:
                self.cookies = json.load(f)
            
            # Save to pickle format
            with open(self.cookie_file, 'wb') as f:
                pickle.dump(self.cookies, f)
            
            logger.info(f"Imported {len(self.cookies)} cookies from {input_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to import cookies: {e}")
            return False
    
    def get_cookies_for_domain(self, domain: str) -> List[Dict[str, Any]]:
        """
        Get cookies for a specific domain
        
        Args:
            domain: Domain to filter cookies for
            
        Returns:
            List of cookies for the domain
        """
        domain_cookies = []
        for cookie in self.cookies:
            cookie_domain = cookie.get('domain', '')
            if domain in cookie_domain or cookie_domain in domain:
                domain_cookies.append(cookie)
        
        return domain_cookies