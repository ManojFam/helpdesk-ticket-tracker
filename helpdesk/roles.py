"""Who is who, decided in one place.

TechCare staff use Django's built-in flags, so the admin site keeps working. `is_staff`
means "works at TechCare" everywhere in the code:
    is_staff + superuser -> ADMIN       (runs TechCare: everything, including /admin/)
    is_staff             -> TECHNICIAN  (works every customer's tickets)
Customers are told apart by their profile:
    profile.is_org_manager  -> ORG_MANAGER (sees all of their organisation's tickets)
    anyone else             -> CUSTOMER    (sees only the tickets they raised)

A customer with an organisation works for a business customer; one without is a
home customer.
"""

ADMIN = "admin"
TECHNICIAN = "technician"
ORG_MANAGER = "org_manager"
CUSTOMER = "customer"

LABELS = {
    ADMIN: "Admin",
    TECHNICIAN: "Technician",
    ORG_MANAGER: "Manager",
    CUSTOMER: "Customer",
}


def organisation_of(user):
    """The customer organisation a user belongs to, or None (staff, home customers)."""
    profile = getattr(user, "profile", None)
    return profile.organisation if profile else None


def role_of(user):
    if user.is_staff:
        return ADMIN if user.is_superuser else TECHNICIAN
    profile = getattr(user, "profile", None)
    if profile and profile.is_org_manager and profile.organisation_id:
        return ORG_MANAGER
    return CUSTOMER
