"""AInstein configuration."""
import os

DB_PATH = os.environ.get('AINSTEIN_DB', '/opt/ainstein/data/ainstein.db')
DATA_DIR = '/opt/ainstein/data/datasets'
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY', '')
DASHSCOPE_BASE_URL = os.environ.get('DASHSCOPE_BASE_URL', 'https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic')
RESEARCH_MODEL = os.environ.get('RESEARCH_MODEL', 'kimi-k2.6')
SCIENTIST_MODEL = os.environ.get('SCIENTIST_MODEL', 'kimi-k2.6')
DIRECTOR_MODEL = os.environ.get('DIRECTOR_MODEL', 'kimi-k2.6')
