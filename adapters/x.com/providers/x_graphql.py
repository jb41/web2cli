"""X.com GraphQL provider for adapter runtime."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from x_client_transaction import ClientTransaction
from x_client_transaction.utils import get_ondemand_file_url

from web2cli.types import AdapterSpec, Request, Session
from web2cli.providers.base import Provider
from web2cli.providers.registry import register_provider
from web2cli.runtime.template import render_value

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)
BASE_URL = "https://x.com/i/api/graphql"
BEARER = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

TIMELINE_FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "post_ctas_fetch_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}

PROFILE_FEATURES = {
    "hidden_profile_subscriptions_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}

FIELD_TOGGLES = {
    "withArticleRichContentState": True,
    "withArticlePlainText": False,
    "withGrokAnalyze": False,
    "withDisallowedReplyControls": False,
}

CACHE_DIR = Path.home() / ".web2cli" / "cache" / "x.com"
CACHE_FILE = CACHE_DIR / "query_ids.json"
_ct: ClientTransaction | None = None


def _extract_tweet_id(raw: str) -> str:
    match = re.search(r"/status/(\d+)", raw)
    if match:
        return match.group(1)
    if raw.strip().isdigit():
        return raw.strip()
    return raw


def _read_cache() -> dict[str, str] | None:
    if CACHE_FILE.is_file():
        try:
            return json.loads(CACHE_FILE.read_text())
        except json.JSONDecodeError:
            return None
    return None


def _fetch_query_ids() -> dict[str, str]:
    resp = httpx.get("https://x.com", headers={"User-Agent": UA}, follow_redirects=True)
    match = re.search(
        r'https://abs\.twimg\.com/responsive-web/client-web/main\.[a-f0-9]+\.js',
        resp.text,
    )
    if not match:
        raise ValueError("Could not find X main JS bundle URL")

    bundle_url = match.group(0)
    bundle = httpx.get(bundle_url, headers={"User-Agent": UA})
    pairs = re.findall(r'queryId:"([^"]+)",operationName:"([^"]+)"', bundle.text)
    if not pairs:
        raise ValueError("Could not extract X query IDs")

    mapping = {op: qid for qid, op in pairs}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(mapping))
    return mapping


def _get_query_id(operation: str, force_refresh: bool = False) -> str:
    if not force_refresh:
        cached = _read_cache()
        if cached and operation in cached:
            return cached[operation]

    mapping = _fetch_query_ids()
    if operation not in mapping:
        raise ValueError(f"X operation '{operation}' not found in current bundle")
    return mapping[operation]


def _init_transaction_client() -> ClientTransaction:
    global _ct
    if _ct is not None:
        return _ct

    headers = {"User-Agent": UA}
    home_resp = httpx.get("https://x.com", headers=headers, follow_redirects=True)
    home_soup = BeautifulSoup(home_resp.text, "html.parser")
    ondemand_url = get_ondemand_file_url(response=home_soup)
    ondemand_resp = httpx.get(ondemand_url, headers=headers)

    _ct = ClientTransaction(
        home_page_response=home_soup,
        ondemand_file_response=ondemand_resp.text,
    )
    return _ct


def _get_transaction_id(method: str, url: str) -> str:
    ct = _init_transaction_client()
    return ct.generate_transaction_id(method=method, path=urlparse(url).path)


def _make_headers(session: Session | None) -> tuple[dict, dict]:
    cookies = {}
    ct0 = ""
    if session and session.data.get("cookies"):
        cookies = dict(session.data["cookies"])
        ct0 = cookies.get("ct0", "")

    headers = {
        "User-Agent": UA,
        "Accept": "*/*",
        "Content-Type": "application/json",
        "authorization": BEARER,
        "x-csrf-token": ct0,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
    }
    return headers, cookies


class XGraphQLProvider(Provider):
    name = "x_graphql"

    def build_request(
        self,
        spec: dict[str, Any],
        ctx: dict[str, Any],
        adapter: AdapterSpec,
        session: Session | None,
    ) -> Request:
        operation = str(spec.get("operation", "")).strip()
        if not operation:
            raise ValueError("x_graphql provider requires 'operation'")

        force_refresh = bool(ctx.get("args", {}).get("_retry"))
        query_id = _get_query_id(operation, force_refresh=force_refresh)

        endpoint = spec.get("endpoint", operation)
        url = f"{BASE_URL}/{query_id}/{endpoint}"

        variables = render_value(spec.get("variables", {}), ctx) or {}
        method = str(render_value(spec.get("method", "GET"), ctx) or "GET").upper()
        features = render_value(spec.get("features"), ctx)
        field_toggles = render_value(spec.get("field_toggles"), ctx)

        # Operation defaults
        if operation == "UserByScreenName":
            if "screen_name" in variables:
                variables["screen_name"] = str(variables["screen_name"]).lstrip("@")
            if features is None:
                features = PROFILE_FEATURES

        if operation == "TweetDetail":
            if "focalTweetId" in variables:
                variables["focalTweetId"] = _extract_tweet_id(str(variables["focalTweetId"]))
            if features is None:
                features = FEATURES
            if field_toggles is None:
                field_toggles = FIELD_TOGGLES

        if operation in {"SearchTimeline"} and features is None:
            features = FEATURES

        if operation in {"HomeTimeline", "HomeLatestTimeline"} and features is None:
            features = TIMELINE_FEATURES

        if operation == "HomeLatestTimeline":
            sort = str(ctx.get("args", {}).get("sort", "recent")).lower()
            ranking = sort == "popular"
            variables.setdefault("enableRanking", ranking)
            method = "POST" if ranking else "GET"
            if not ranking:
                variables.setdefault("requestContext", "ptr")

        if features is None:
            features = FEATURES

        headers, cookies = _make_headers(session)
        headers.update(render_value(spec.get("headers", {}), ctx) or {})
        if spec.get("use_transaction", True):
            headers["x-client-transaction-id"] = _get_transaction_id(method, url)

        if method == "POST":
            body = {"variables": variables, "features": features, "queryId": query_id}
            if field_toggles:
                body["fieldToggles"] = field_toggles
            return Request(
                method=method,
                url=url,
                headers=headers,
                cookies=cookies,
                body=body,
                content_type="application/json",
            )

        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(features),
        }
        if field_toggles:
            params["fieldToggles"] = json.dumps(field_toggles)

        return Request(
            method=method,
            url=url,
            params=params,
            headers=headers,
            cookies=cookies,
        )


register_provider(XGraphQLProvider())
