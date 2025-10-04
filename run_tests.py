#!/usr/bin/env python3
"""
Test runner for quiz generation tests with mock environment variables.
"""
import os
import sys

# Set dummy environment variables required by app.py
os.environ['DISCORD_TOKEN'] = 'test_token'
os.environ['OPENAI_API_KEY'] = 'test_key'
os.environ['ASSISTANT_ID'] = 'test_assistant_id'

# Now run the tests
import unittest

# Add tests directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import test module
from tests.test_generate_quiz import *

if __name__ == '__main__':
    unittest.main(module='tests.test_generate_quiz', verbosity=2)
