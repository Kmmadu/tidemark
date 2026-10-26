import yaml
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from git import Repo

logger = logging.getLogger(__name__)

# Load environment variables - REMOVED: now called explicitly by load_env()
# load_dotenv()

def load_env():
    """Load environment variables from .env file"""
    load_dotenv()
    logger.info("Environment variables loaded")

def get_required_env(key: str) -> str:
    """Get required environment variable or raise error"""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Missing required environment variable: {key}")
    return value

def setup_logging(level: str = "INFO"):
    """Configure logging to file and console"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / "backup.log"),
            logging.StreamHandler()
        ]
    )
    logger.info(f"Logging configured at {level} level")

def load_devices(yaml_file="config/devices.yaml"):
    """
    Load device inventory from YAML file.
    
    Args:
        yaml_file (str): Path to YAML inventory file
    
    Returns:
        list: List of device dictionaries with credentials added
    """
    try:
        with open(yaml_file, "r") as f:
            data = yaml.safe_load(f)
        
        devices = data.get("devices", [])
        # Add credentials from environment variables
        username = os.getenv("DEVICE_USERNAME")
        password = os.getenv("DEVICE_PASSWORD")
        secret = os.getenv("DEVICE_SECRET")
        
        for device in devices:
            device["username"] = username
            device["password"] = password
            if secret:
                device["secret"] = secret
            
            # Ensure port is included if specified
            if 'port' not in device:
                device['port'] = 22  # Default SSH port
        
        logger.info(f"Loaded {len(devices)} devices from {yaml_file}")
        for device in devices:
            logger.debug(f"  - {device.get('name', device['host'])}: {device['host']}:{device.get('port', 22)}")
        return devices
    except Exception as e:
        logger.error(f"Failed to load devices: {e}")
        return []

def git_commit_and_push(repo_path=".", commit_message="Automated backup"):
    """
    Commit and push all changes to Git repository.
    
    Args:
        repo_path (str): Path to Git repository root
        commit_message (str): Message for the commit
    """
    try:
        repo = Repo(repo_path)
        # Add all changes
        repo.git.add(A=True)
        
        # Check if there are changes to commit
        if repo.index.diff("HEAD"):
            repo.index.commit(commit_message)
            origin = repo.remote(name="origin")
            origin.push()
            logger.info(f"Successfully pushed to Git: {commit_message}")
        else:
            logger.info("No changes to commit")
    except Exception as e:
        logger.error(f"Git operation failed: {e}")