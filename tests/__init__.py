# Lets `python3 -m unittest tests.test_x` find the test modules' sibling `import hermetic`, as discover -s tests does.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
