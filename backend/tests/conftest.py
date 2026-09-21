import os, sys
os.environ.setdefault("SUPER_ADMIN_ID", "root")
os.environ.setdefault("SUPER_ADMIN_PASSWORD", "x")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("DEBUG_MODE", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
