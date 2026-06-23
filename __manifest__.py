{
    "name": "NN Fund Management",
    "version": "18.0.1.0.0",
    "category": "Accounting/Finance",
    "summary": "Enterprise fund management system with ledger-based accounting",
    "description": """
NN Fund Management
==================
Enterprise-grade fund management system with full audit trail,
double-spending prevention, and configurable approval workflows.

Key Features:
- Fund Account Management with Ledger-Based Architecture
- Incoming Fund Tracking with Bank Email Integration
- Fund Allocations with Approval Workflow
- Project and Expense Head Management
- Requisition and Bill Management
- Fund Transfers
- Configurable Approval Engine (GM/MD/Finance/Board)
- Dynamic Approval Matrix
- Real-time Balance Computation from Ledger
- Double-Spending Prevention
- Full Audit Trail and Activity Tracking
- Multi-Company Support
- Dashboard with Real-time Metrics
- REST API with OAuth2 Authentication
- Production Docker Deployment
- CI/CD Pipeline with Automated Testing
- Performance Optimized (Indexes, SQL Optimization)
- Scheduled Jobs for Validation and Reporting
- Backup & Recovery Automation
- Monitoring & Health Checks
    """,
    "author": "Md. Ripon Molla, NN Services & Engineering Ltd",
    "website": "https://github.com/anomalyco/nn_fund_management",
    "depends": [
        "base",
        "mail",
        "account",
        "web",
    ],
    "data": [
        "security/security_groups.xml",
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "security/security_hardening.xml",
        "data/sequence_data.xml",
        "data/security_data.xml",
        "data/cron_data.xml",
        "views/fund_account_views.xml",
        "views/fund_ledger_views.xml",
        "views/incoming_fund_views.xml",
        "views/project_views.xml",
        "views/expense_head_views.xml",
        "views/fund_allocation_views.xml",
        "views/fund_requisition_views.xml",
        "views/fund_bill_views.xml",
        "views/fund_transfer_views.xml",
        "views/approval_rule_views.xml",
        "views/approval_history_views.xml",
        "views/audit_log_views.xml",
        "views/dashboard_views.xml",
        "views/report_views.xml",
        "views/bank_email_views.xml",
        "views/approval_matrix_views.xml",
        "views/ledger_reconciliation_views.xml",
        "views/login_views.xml",
        "views/menus.xml",
    ],
    "demo": [
        "data/demo_data.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "MIT",
}
