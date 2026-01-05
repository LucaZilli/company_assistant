import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
OPENROUTER_BASE_URL = os.getenv('OPENROUTER_BASE_URL')

GENERATOR_MODEL_NAME = os.getenv('GENERATOR_MODEL_NAME')
ORCHESTRATOR_MODEL_NAME = os.getenv('ORCHESTRATOR_MODEL_NAME')

KNOWLEDGE_BASE_DIR = BASE_DIR / 'knowledge_base'

SERPER_API_KEY = os.getenv('SERPER_API_KEY')
SEARCH_MODEL_NAME = os.getenv('SEARCH_MODEL_NAME')


CACHE_ENABLED = os.getenv('CACHE_ENABLED', 'True').lower() == 'true'
CACHE_TTL_DAYS = int(os.getenv('CACHE_TTL_DAYS', '30'))
DATABASE_URL = os.getenv('DATABASE_URL', '')

EVALUATION_MODEL_NAME = os.getenv('EVALUATION_MODEL_NAME', 'openai/gpt-4.1')
