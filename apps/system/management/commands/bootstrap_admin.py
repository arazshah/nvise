import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the initial admin user if it does not already exist."

    def handle(self, *args, **options):
        username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin")
        password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "adminpass123")
        email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "")

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )

        if created:
            user.set_password(password)
            user.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(f"Created bootstrap admin user: {username}"))
            return

        self.stdout.write(f"Bootstrap admin user already exists: {username}; leaving it unchanged.")
