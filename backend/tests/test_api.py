import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base, get_db
from main import app

import os

TEST_DB_FILE = "test_insightz.db"

# Setup isolated file-based SQLite database for API integration tests
engine = create_engine(
    f"sqlite:///{TEST_DB_FILE}", 
    connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

# Register dependency overrides
app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(autouse=True)
def init_test_db():
    # Remove existing test db if any left over
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except OSError:
            pass
            
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    
    # Clean up test db file
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except OSError:
            pass

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

def test_signup_validation_failures():
    # Password too short (3 chars)
    response = client.post("/signup", json={"username": "validuser", "password": "abc"})
    assert response.status_code == 422
    
    # Username with invalid spaces
    response = client.post("/signup", json={"username": "test user", "password": "validpassword"})
    assert response.status_code == 422

def test_signup_and_login_flow():
    # Register new tenant
    response = client.post("/signup", json={"username": "ranger_bob", "password": "bob_secure_password"})
    assert response.status_code == 200
    assert response.json() == {"message": "Ranger registered successfully"}
    
    # Reject duplicate registrations
    response = client.post("/signup", json={"username": "ranger_bob", "password": "another_secure_password"})
    assert response.status_code == 400
    
    # Log in with correct credentials
    response = client.post("/login", json={"username": "ranger_bob", "password": "bob_secure_password"})
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["username"] == "ranger_bob"
    
    # Reject log in with incorrect credentials
    response = client.post("/login", json={"username": "ranger_bob", "password": "wrong_password"})
    assert response.status_code == 401

def test_protected_routes_unauthorized():
    response = client.get("/documents")
    assert response.status_code == 401
