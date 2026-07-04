"""Unit tests for the false-inability hallucination guard."""

from clio.agent.core import _claims_false_inability


class TestDetectsFalseInabilityClaims:
    def test_no_write_access_to_repository(self):
        # The exact hallucination observed live from qwen3-coder
        assert _claims_false_inability(
            "However, since I don't have write access to the repository, "
            "I can't actually perform the git operations."
        )

    def test_cannot_run_commands(self):
        assert _claims_false_inability("I cannot run shell commands in this environment.")
        assert _claims_false_inability("I'm unable to execute git commands directly.")

    def test_cannot_commit_or_push(self):
        assert _claims_false_inability("I can't commit the repository myself.")
        assert _claims_false_inability("I cannot directly modify your files.")

    def test_lacks_permissions(self):
        assert _claims_false_inability(
            "I don't have the necessary permissions to push to the remote."
        )

    def test_proper_credentials_deflection(self):
        assert _claims_false_inability(
            "The commit would need to be done with proper credentials."
        )


class TestDoesNotFireOnHonestStatements:
    def test_normal_answers(self):
        assert not _claims_false_inability("The latest commit is 8ed319a.")
        assert not _claims_false_inability("Changed X to Y in src/app.py.")
        assert not _claims_false_inability("")
        assert not _claims_false_inability(None)

    def test_true_external_inabilities(self):
        # Statements about external systems the agent genuinely can't reach
        assert not _claims_false_inability(
            "I don't have access to your AWS account, so I checked the local config instead."
        )
        assert not _claims_false_inability(
            "I can't see your browser session; paste the error here."
        )

    def test_talking_about_permissions_factually(self):
        # Describing the permission system is not claiming inability
        assert not _claims_false_inability(
            "State-changing commands show you a permission prompt before running."
        )

    def test_user_facing_error_reporting(self):
        assert not _claims_false_inability(
            "The command failed: fatal: not a git repository."
        )
