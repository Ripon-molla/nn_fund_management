import logging

from odoo import api, fields, models, _, Command

_logger = logging.getLogger(__name__)


class FundDashboard(models.Model):
    _name = "nn.fund.dashboard"
    _description = "Fund Dashboard"
    _rec_name = "name"
    _auto = False
    _log_access = False

    def create(self, vals):
        _logger.warning("Blocked attempt to CREATE a read-only dashboard record")
        return self.new(vals)

    def write(self, vals):
        _logger.warning("Blocked attempt to WRITE to a read-only dashboard record")
        return True

    def unlink(self):
        _logger.warning("Blocked attempt to DELETE a read-only dashboard record")
        return True

    def copy(self, default=None):
        return self

    @api.model
    def load_views(self, views, options=None):
        res = super().load_views(views, options=options)
        return res

    def web_save(self, vals, specification, next_id=None, save_dirty=False):
        _logger.info("Dashboard web_save — returning fresh KPI data")
        fresh = self.default_get(list(specification)) if specification else self.default_get([])
        record = {"id": -1}
        for field_name, field_spec in specification.items():
            field = self._fields.get(field_name)
            if field is None:
                continue
            val = fresh.get(field_name, field.default)
            if field.type == "many2one":
                record[field_name] = (val, self.env[field.comodel_name].browse(val).display_name) if val else False
            else:
                record[field_name] = val
        return [record]

    def onchange(self, values, field_name, field_onchange):
        _logger.info("Dashboard onchange computed (field: %s)", field_name)
        return super().onchange(values, field_name, field_onchange)

    name = fields.Char(string="Name", default=lambda self: _("Finance Dashboard"))

    # ── KPI Fields ──────────────────────────────────────────────
    total_funds_received = fields.Monetary(
        string="Total Funds Received",
        currency_field="currency_id",
    )
    unassigned_balance = fields.Monetary(
        string="Available Balance",
        currency_field="currency_id",
    )
    held_balance = fields.Monetary(
        string="Held Balance",
        currency_field="currency_id",
    )
    assigned_balance = fields.Monetary(
        string="Assigned Balance",
        currency_field="currency_id",
    )
    spent_balance = fields.Monetary(
        string="Spent Amount",
        currency_field="currency_id",
    )
    pending_approvals_count = fields.Integer(
        string="Pending Approvals",
    )

    # ── Extra Counts ────────────────────────────────────────────
    pending_allocations_count = fields.Integer(string="Pending Allocations")
    pending_requisitions_count = fields.Integer(string="Pending Requisitions")
    pending_transfers_count = fields.Integer(string="Pending Transfers")
    active_projects_count = fields.Integer(string="Active Projects")
    fund_accounts_count = fields.Integer(string="Fund Accounts")

    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
    )

    # ── Tables ──────────────────────────────────────────────────
    recent_transactions = fields.Many2many(
        comodel_name="nn.fund.ledger",
        relation="nn_fund_dashboard_recent_transactions",
        string="Recent Fund Movements",
    )

    recent_approvals = fields.Many2many(
        comodel_name="nn.approval.history",
        relation="nn_fund_dashboard_recent_approvals",
        string="Recent Approvals",
    )

    project_balances = fields.Many2many(
        comodel_name="nn.project",
        relation="nn_fund_dashboard_project_balances",
        string="Project Balances",
    )

    expense_head_balances = fields.Many2many(
        comodel_name="nn.expense.head",
        relation="nn_fund_dashboard_expense_head_balances",
        string="Expense Head Balances",
    )

    # ── Charts (SQL-view models) ────────────────────────────────
    monthly_incoming_chart_ids = fields.Many2many(
        comodel_name="nn.dashboard.monthly.incoming",
        relation="nn_fund_dashboard_monthly_incoming_rel",
        string="Monthly Incoming Funds",
    )

    allocation_dist_chart_ids = fields.Many2many(
        comodel_name="nn.dashboard.allocation.dist",
        relation="nn_fund_dashboard_allocation_dist_rel",
        string="Allocation Distribution",
    )

    spending_dist_chart_ids = fields.Many2many(
        comodel_name="nn.dashboard.spending.dist",
        relation="nn_fund_dashboard_spending_dist_rel",
        string="Spending Distribution",
    )

    # ── default_get ─────────────────────────────────────────────
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env.company
        Ledger = self.env["nn.fund.ledger"]
        Account = self.env["nn.fund.account"]
        Allocation = self.env["nn.fund.allocation"]
        Project = self.env["nn.project"]
        ExpenseHead = self.env["nn.expense.head"]
        ApprovalHistory = self.env["nn.approval.history"]
        Requisition = self.env["nn.fund.requisition"]
        Transfer = self.env["nn.fund.transfer"]
        Bill = self.env["nn.fund.bill"]

        accounts = Account.search([("company_id", "=", company.id)])
        total_funds = sum(
            Ledger.search(
                [
                    ("fund_account_id", "in", accounts.ids),
                    ("state", "=", "posted"),
                    ("debit", ">", 0),
                    ("reference_model", "=", "nn.incoming.fund"),
                ]
            ).mapped("debit")
        )

        res["total_funds_received"] = total_funds
        res["unassigned_balance"] = sum(accounts.mapped("available_balance"))
        res["held_balance"] = sum(accounts.mapped("held_balance"))
        res["assigned_balance"] = sum(accounts.mapped("assigned_balance"))
        res["spent_balance"] = sum(accounts.mapped("spent_balance"))
        res["currency_id"] = company.currency_id.id
        res["fund_accounts_count"] = len(accounts)

        projects = Project.search(
            [("company_id", "=", company.id), ("active", "=", True)]
        )
        res["active_projects_count"] = len(projects)

        pending_states = ["submitted", "pending_approval"]
        pending_allocations = Allocation.search(
            [("company_id", "=", company.id), ("state", "in", pending_states)]
        )
        pending_requisitions = Requisition.search(
            [("company_id", "=", company.id), ("state", "in", pending_states)]
        )
        pending_transfers = Transfer.search(
            [("company_id", "=", company.id), ("state", "in", pending_states)]
        )
        res["pending_allocations_count"] = len(pending_allocations)
        res["pending_requisitions_count"] = len(pending_requisitions)
        res["pending_transfers_count"] = len(pending_transfers)
        res["pending_approvals_count"] = (
            len(pending_allocations)
            + len(pending_requisitions)
            + len(pending_transfers)
        )

        res["recent_transactions"] = [Command.set(
            Ledger.search(
                [("state", "=", "posted")], order="date DESC, id DESC", limit=10
            ).ids
        )]

        res["project_balances"] = [Command.set(projects.ids)]

        expense_heads = ExpenseHead.search(
            [("company_id", "=", company.id), ("active", "=", True)]
        )
        res["expense_head_balances"] = [Command.set(expense_heads.ids)]

        res["recent_approvals"] = [Command.set(
            ApprovalHistory.search(
                [], order="date DESC, id DESC", limit=10
            ).ids
        )]

        res["monthly_incoming_chart_ids"] = [Command.set(
            self.env["nn.dashboard.monthly.incoming"].search(
                [], order="month ASC"
            ).ids
        )]

        res["allocation_dist_chart_ids"] = [Command.set(
            self.env["nn.dashboard.allocation.dist"].search(
                [], order="amount DESC"
            ).ids
        )]

        res["spending_dist_chart_ids"] = [Command.set(
            self.env["nn.dashboard.spending.dist"].search(
                [], order="amount DESC"
            ).ids
        )]

        return res

    def action_open_dashboard(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Fund Dashboard"),
            "res_model": "nn.fund.dashboard",
            "view_mode": "form",
            "target": "inline",
            "context": {"create": False, "edit": False, "no_dashboard_save": True},
        }


# ────────────────────────────────────────────────────────────────
#  CHART SQL-VIEW MODELS
# ────────────────────────────────────────────────────────────────

class MonthlyIncomingChart(models.Model):
    _name = "nn.dashboard.monthly.incoming"
    _description = "Monthly Incoming Funds"
    _auto = False
    _log_access = False

    month = fields.Char(string="Month", readonly=True)
    amount = fields.Monetary(
        string="Amount", readonly=True, currency_field="currency_id"
    )
    currency_id = fields.Many2one(
        "res.currency", string="Currency", readonly=True
    )

    def init(self):
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW nn_dashboard_monthly_incoming AS (
                SELECT
                    ROW_NUMBER() OVER () AS id,
                    TO_CHAR(l.date AT TIME ZONE 'UTC', 'YYYY-MM') AS month,
                    SUM(l.debit) AS amount,
                    MIN(c.currency_id) AS currency_id
                FROM nn_fund_ledger l
                JOIN nn_fund_account a ON l.fund_account_id = a.id
                JOIN res_company c ON a.company_id = c.id
                WHERE l.state = 'posted'
                    AND l.reference_model = 'nn.incoming.fund'
                    AND l.debit > 0
                GROUP BY TO_CHAR(l.date AT TIME ZONE 'UTC', 'YYYY-MM')
                ORDER BY month
            )
        """)


class AllocationDistChart(models.Model):
    _name = "nn.dashboard.allocation.dist"
    _description = "Allocation Distribution"
    _auto = False
    _log_access = False

    project_name = fields.Char(string="Project", readonly=True)
    amount = fields.Monetary(
        string="Allocated", readonly=True, currency_field="currency_id"
    )
    currency_id = fields.Many2one(
        "res.currency", string="Currency", readonly=True
    )

    def init(self):
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW nn_dashboard_allocation_dist AS (
                SELECT
                    ROW_NUMBER() OVER () AS id,
                    COALESCE(p.display_name, 'No Project') AS project_name,
                    SUM(l.credit) AS amount,
                    MIN(c.currency_id) AS currency_id
                FROM nn_fund_ledger l
                LEFT JOIN nn_project p ON l.project_id = p.id
                JOIN nn_fund_account a ON l.fund_account_id = a.id
                JOIN res_company c ON a.company_id = c.id
                WHERE l.state = 'posted'
                    AND l.transaction_type = 'allocation_approve'
                    AND l.credit > 0
                GROUP BY p.display_name
                ORDER BY amount DESC
            )
        """)


class SpendingDistChart(models.Model):
    _name = "nn.dashboard.spending.dist"
    _description = "Spending Distribution"
    _auto = False
    _log_access = False

    project_name = fields.Char(string="Project", readonly=True)
    amount = fields.Monetary(
        string="Spent", readonly=True, currency_field="currency_id"
    )
    currency_id = fields.Many2one(
        "res.currency", string="Currency", readonly=True
    )

    def init(self):
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW nn_dashboard_spending_dist AS (
                SELECT
                    ROW_NUMBER() OVER () AS id,
                    COALESCE(p.display_name, 'No Project') AS project_name,
                    SUM(l.credit) AS amount,
                    MIN(c.currency_id) AS currency_id
                FROM nn_fund_ledger l
                LEFT JOIN nn_project p ON l.project_id = p.id
                JOIN nn_fund_account a ON l.fund_account_id = a.id
                JOIN res_company c ON a.company_id = c.id
                WHERE l.state = 'posted'
                    AND l.transaction_type IN ('bill_posted', 'requisition_approved')
                    AND l.credit > 0
                GROUP BY p.display_name
                ORDER BY amount DESC
            )
        """)
