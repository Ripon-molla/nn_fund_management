from odoo import api, fields, models, _


class NotificationMixin(models.AbstractModel):
    _name = "nn.notification.mixin"
    _description = "Notification Mixin"

    def _get_requester(self):
        self.ensure_one()
        if hasattr(self, "requested_by") and self.requested_by:
            return self.requested_by
        return self.create_uid

    def _notify_requester(self, subject, message):
        self.ensure_one()
        requester = self._get_requester()
        if requester and requester != self.env.user:
            self.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=subject,
                note=message,
                user_id=requester.id,
            )

    def _notify_approvers(self, line, subject, message):
        self.ensure_one()
        approvers = line._get_approvers()
        for user in approvers:
            self.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=subject,
                note=message,
                user_id=user.id,
            )

    def _notify_group(self, group_xml_id, subject, message):
        self.ensure_one()
        group = self.env.ref(group_xml_id, raise_if_not_found=False)
        if not group:
            return
        for user in group.users:
            if user != self.env.user:
                self.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=subject,
                    note=message,
                    user_id=user.id,
                )
