import logging
import uuid
from typing import Optional, Dict, Any
from src.modules.infra.sqlite_repository import get_repository
from src.modules.auth.password_hasher import hash_password, verify_password
from src.modules.auth.jwt_manager import create_access_token, decode_access_token

logger = logging.getLogger("src.services.user_auth_service")

class UserAuthService:
    """Orchestrator for user authentication, registration, and authorization."""

    def __init__(self, repo=None):
        self.repo = repo or get_repository()

    def register(self, username: str, email: str, password: str, role: str = "user", cloudinary_url: Optional[str] = None) -> Dict[str, Any]:
        """Register a new user after verifying uniqueness."""
        logger.info("[user_auth_service.register] Attempting registration for username=%s, email=%s", username, email)
        
        # Check existing username
        if self.repo.get_user_by_username(username):
            logger.warning("[user_auth_service.register] Username '%s' already exists", username)
            raise ValueError(f"Username '{username}' is already taken")

        # Check existing email
        if self.repo.get_user_by_email(email):
            logger.warning("[user_auth_service.register] Email '%s' already registered", email)
            raise ValueError(f"Email '{email}' is already registered")

        user_id = f"user_{uuid.uuid4().hex[:12]}"
        hashed_pw = hash_password(password)

        created = self.repo.create_user(
            user_id=user_id,
            username=username,
            email=email,
            hashed_password=hashed_pw,
            role=role,
            cloudinary_url=cloudinary_url
        )
        if not created:
            logger.error("[user_auth_service.register] Failed to save user to database")
            raise RuntimeError("Database error while creating user")

        user = self.repo.get_user_by_id(user_id)
        logger.info("[user_auth_service.register] Successfully registered user_id=%s", user_id)
        return user

    def authenticate(self, username_or_email: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user credentials and return user record if valid."""
        logger.info("[user_auth_service.authenticate] Authenticating user: %s", username_or_email)
        
        user = self.repo.get_user_by_username(username_or_email)
        if not user:
            user = self.repo.get_user_by_email(username_or_email)

        if not user:
            logger.warning("[user_auth_service.authenticate] User not found: %s", username_or_email)
            return None

        if not verify_password(password, user["hashed_password"]):
            logger.warning("[user_auth_service.authenticate] Invalid password for: %s", username_or_email)
            return None

        logger.info("[user_auth_service.authenticate] User authenticated successfully: %s", user["user_id"])
        return user

    def issue_token(self, user: Dict[str, Any]) -> str:
        """Issue a JWT access token for the given user."""
        token_data = {
            "sub": user["user_id"],
            "username": user["username"],
            "role": user.get("role", "user")
        }
        token = create_access_token(data=token_data)
        logger.info("[user_auth_service.issue_token] Issued token for user_id=%s", user["user_id"])
        return token

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate token and return user data if valid."""
        payload = decode_access_token(token)
        if not payload or "sub" not in payload:
            logger.warning("[user_auth_service.verify_token] Invalid or expired token")
            return None
        
        user = self.repo.get_user_by_id(payload["sub"])
        return user

    def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve user profile by ID."""
        return self.repo.get_user_by_id(user_id)

    def update_cloudinary_url(self, user_id: str, cloudinary_url: str) -> bool:
        """Update Cloudinary URL on the user's profile."""
        logger.info("[user_auth_service.update_cloudinary_url] Updating Cloudinary credentials for user_id=%s", user_id)
        return self.repo.update_user_cloudinary_url(user_id, cloudinary_url)


_auth_service_instance: Optional[UserAuthService] = None

def get_auth_service() -> UserAuthService:
    global _auth_service_instance
    if _auth_service_instance is None:
        _auth_service_instance = UserAuthService()
    return _auth_service_instance

