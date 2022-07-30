import os
import json
from time import sleep
from dataclasses import dataclass

from httpx import Timeout, Limits, HTTPTransport, Client


@dataclass
class IssueConfig:
    name: str
    channel_id: int
    discussion_id: int
    bot_token: str
    last_update_id: int = 0


class TelegramClient:
    def __init__(self, config_path):
        assert os.path.exists(config_path)
        with open(config_path) as r:
            self.config = json.load(r)

        timeout = Timeout(
            connect=self.config.get("connect_timeout", 10.0),
            read=self.config.get("read_timeout", 10.0),
            write=self.config.get("write_timeout", 10.0),
            pool=self.config.get("pool_timeout", 1.0),
        )
        limits = Limits(
            max_connections=self.config.get("connection_pool_size", 1),
            max_keepalive_connections=self.config.get("connection_pool_size", 1),
        )
        transport = HTTPTransport(
            retries=self.config.get("retries", 5)
        )
        self.client = Client(
            timeout=timeout,
            limits=limits,
            transport=transport
        )

        self.issues = {config["name"]: IssueConfig(**config) for config in self.config["issues"]}
        self.discussions = {issue.name: dict() for _, issue in self.issues.items()}
        for issue_name in self.issues:
            self.update_discussion_mapping(issue_name)

    def send_message(self, text, issue_name, photos=tuple(), videos=tuple()):
        issue = self.issues[issue_name]
        if len(photos) == 1:
            return self._send_photo(text, photos[0], issue=issue)
        elif len(photos) > 1:
            return self._send_photos(text, photos, issue=issue)
        elif len(videos) >= 1:
            return self._send_video(text, videos[0], issue=issue)
        return self._send_text(text, issue=issue)

    def update_message(self, message_id, text, is_caption, issue_name):
        issue = self.issues[issue_name]
        if not is_caption:
            return self._edit_text(message_id, text, issue=issue)
        return self._edit_caption(message_id, text, issue=issue)

    def update_discussion_mapping(self, issue_name):
        issue = self.issues[issue_name]
        updates = self._get_updates(issue)
        if not updates:
            return dict()
        for update in updates:
            if "message" not in update:
                continue
            message = update["message"]
            if "forward_from_chat" not in message:
                continue
            if issue.channel_id != message["forward_from_chat"]["id"]:
                continue
            if issue.discussion_id != message["chat"]["id"]:
                continue
            orig_message_id = message["forward_from_message_id"]
            discussion_message_id = message["message_id"]
            self.discussions[issue.name][orig_message_id] = discussion_message_id

    def get_discussion(self, message_id, issue_name):
        return self.discussions[issue_name].get(message_id, None)

    def send_discussion_message(self, text, reply_to_message_id, issue_name):
        issue = self.issues[issue_name]
        if not issue.discussion_id or not reply_to_message_id:
            return None
        url_template = "https://api.telegram.org/bot{}/sendMessage"
        params = {
            "chat_id": issue.discussion_id,
            "text": text,
            "parse_mode": "html",
            "disable_web_page_preview": False,
            "reply_to_message_id": reply_to_message_id
        }
        return self._post(url_template.format(issue.bot_token), params)

    def _send_text(self, text, issue):
        url_template = "https://api.telegram.org/bot{}/sendMessage"
        params = {
            "chat_id": issue.channel_id,
            "text": text,
            "parse_mode": "html",
            "disable_web_page_preview": True,
            "disable_notification": True
        }
        return self._post(url_template.format(issue.bot_token), params)

    def _send_photo(self, text, photo, issue):
        url_template = "https://api.telegram.org/bot{}/sendPhoto"
        params = {
            "chat_id": issue.channel_id,
            "caption": text,
            "photo": photo,
            "parse_mode": "html",
            "disable_notification": True
        }
        return self._post(url_template.format(issue.bot_token), params)

    def _send_video(self, text, video, issue):
        url_template = "https://api.telegram.org/bot{}/sendVideo"
        params = {
            "chat_id": issue.channel_id,
            "caption": text,
            "video": video,
            "parse_mode": "html",
            "disable_notification": True
        }
        return self._post(url_template.format(issue.bot_token), params)

    def _send_photos(self, text, photos, issue):
        url_template = "https://api.telegram.org/bot{}/sendMediaGroup"
        media = [{
            "type": "photo",
            "media": photo,
            "caption": text if i == 0 else "",
            "parse_mode": "html"
        } for i, photo in enumerate(photos)]
        params = {
            "chat_id": issue.channel_id,
            "disable_notification": True,
            "media": json.dumps(media)
        }
        return self._post(url_template.format(issue.bot_token), params)

    def _edit_text(self, message_id, text, issue):
        url_template = "https://api.telegram.org/bot{}/editMessageText"
        params = {
            "chat_id": issue.channel_id,
            "text": text,
            "parse_mode": "html",
            "disable_web_page_preview": True,
            "message_id": message_id
        }
        return self._post(url_template.format(issue.bot_token), params)

    def _edit_caption(self, message_id, text, issue):
        url_template = "https://api.telegram.org/bot{}/editMessageCaption"
        params = {
            "chat_id": issue.channel_id,
            "message_id": message_id,
            "caption": text,
            "parse_mode": "html",
        }
        return self._post(url_template.format(issue.bot_token), params)

    def _get_updates(self, issue):
        url_template = "https://api.telegram.org/bot{}/getUpdates"
        params = {
            "timeout": 10
        }
        if issue.last_update_id != 0:
            params["offset"] = issue.last_update_id
        response = self.client.get(url_template.format(issue.bot_token), params=params, timeout=20)
        if response.status_code != 200:
            return None
        updates = response.json()["result"]
        for update in updates:
            issue.last_update_id = max(issue.last_update_id, update["update_id"]) + 1
        return updates

    def _post(self, url, params):
        return self.client.post(url, data=params)
