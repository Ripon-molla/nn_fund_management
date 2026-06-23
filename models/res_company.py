import logging
from odoo import models

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'
