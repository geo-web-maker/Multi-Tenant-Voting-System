"""Certificate look per organisation: unknown ids fall back to classic, and old clients cannot reset the choice."""
import main


def test_unknown_or_missing_template_is_classic():
    assert main._doc_template("formal") == "formal"
    assert main._doc_template("classic") == "classic"
    assert main._doc_template(None) == "classic"
    assert main._doc_template("../etc/passwd") == "classic"


def test_branding_update_leaves_template_unset_when_the_client_omits_it():
    data = main.BrandingUpdate(logo_url="", primary_color="#003366", accent_color="#f1c40f")
    assert data.document_template is None
