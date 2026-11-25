"""Create the existing ClaimGuard PostgreSQL schema."""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="user"),
        sa.Column("is_verified", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text()),
        sa.Column("extra_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index("idx_users_email", "users", ["email"])

    op.create_table(
        "otp_records",
        sa.Column("email", sa.Text(), primary_key=True),
        sa.Column("otp", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
    )

    op.create_table(
        "invoices",
        sa.Column("invoice_id", sa.String(), primary_key=True),
        sa.Column("uploaded_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("invoice_number", sa.Text()),
        sa.Column("vendor_name", sa.Text()),
        sa.Column("invoice_date", sa.Text()),
        sa.Column("total_amount", sa.Float()),
        sa.Column("status", sa.Text()),
        sa.Column("risk_score", sa.Float()),
        sa.Column("risk_level", sa.Text()),
        sa.Column("uploaded_at", sa.Text()),
        sa.Column("record_json", sa.Text(), nullable=False),
    )
    op.create_index("idx_invoices_uploaded_by", "invoices", ["uploaded_by"])
    op.create_index("idx_invoices_uploaded_at", "invoices", ["uploaded_at"])
    op.create_index("idx_invoices_status", "invoices", ["status"])

    op.create_table(
        "invoice_documents",
        sa.Column("invoice_id", sa.String(), sa.ForeignKey("invoices.invoice_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("original_filename", sa.Text()),
        sa.Column("stored_filename", sa.Text()),
        sa.Column("file_path", sa.Text()),
        sa.Column("file_size", sa.Integer()),
        sa.Column("file_extension", sa.Text()),
    )

    op.create_table(
        "invoice_anomalies",
        sa.Column("anomaly_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("invoice_id", sa.String(), sa.ForeignKey("invoices.invoice_id", ondelete="CASCADE"), nullable=False),
        sa.Column("anomaly_type", sa.Text()),
        sa.Column("severity", sa.Text()),
        sa.Column("score_contribution", sa.Float()),
        sa.Column("message", sa.Text()),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index("idx_invoice_anomalies_invoice_id", "invoice_anomalies", ["invoice_id"])

    op.create_table(
        "invoice_decisions",
        sa.Column("decision_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("invoice_id", sa.String(), sa.ForeignKey("invoices.invoice_id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("decision_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("invoice_decisions")
    op.drop_index("idx_invoice_anomalies_invoice_id", table_name="invoice_anomalies")
    op.drop_table("invoice_anomalies")
    op.drop_table("invoice_documents")
    op.drop_index("idx_invoices_status", table_name="invoices")
    op.drop_index("idx_invoices_uploaded_at", table_name="invoices")
    op.drop_index("idx_invoices_uploaded_by", table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("otp_records")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")
