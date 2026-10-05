#!/usr/bin/env python3
"""
Homebox MCP Server
==================
FastMCP HTTP server providing READ-ONLY MCP tools (all HTTP GET) for the Homebox inventory API.
Homebox is the source of truth; this server never creates, changes or deletes anything.

Targets Homebox v0.26+ (entity merge): items and locations are both "entities"
under /api/v1/entities, and labels are "tags" under /api/v1/tags.
Ref: Homebox docs, "API Migration Guide - Entity Merge".

Environment Variables:
    HOMEBOX_URL: Homebox base URL (default: http://localhost:7745)
    HOMEBOX_EMAIL: Homebox account email (required)
    HOMEBOX_PASSWORD: Homebox account password (required)
    SERVER_HOST: Server bind address (default: 0.0.0.0)
    SERVER_PORT: Server port (default: 8031)
"""

import os
import json
import logging
import sys
from typing import List, Dict, Any
from datetime import datetime, timedelta
import requests
from fastmcp import FastMCP

# Configure logging to stdout for journald
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('homebox-mcp')


class HomeboxClient:
    """Client for interacting with the Homebox API (v0.26+)."""

    def __init__(self, base_url: str, email: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.email = email
        self.password = password
        self.token = None
        self.token_expires = None
        self.session = requests.Session()
        logger.info(f"HomeboxClient initialized for {self.base_url}")

    def _get_token(self) -> str:
        """Get authentication token, refreshing if necessary."""
        if self.token and self.token_expires:
            if datetime.now() < (self.token_expires - timedelta(hours=1)):
                return self.token

        logger.info("Authenticating with Homebox API")
        auth_url = f"{self.base_url}/api/v1/users/login"
        try:
            response = self.session.post(
                auth_url,
                json={"username": self.email, "password": self.password},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            self.token = data.get("token")
            if not self.token:
                raise Exception("No token in authentication response")
            self.token_expires = datetime.now() + timedelta(hours=23)
            logger.info("Successfully authenticated with Homebox")
            return self.token
        except requests.exceptions.RequestException as e:
            logger.error(f"Authentication failed: {str(e)}")
            raise Exception(f"Failed to authenticate with Homebox: {str(e)}")

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make an authenticated request to the Homebox API."""
        token = self._get_token()
        url = f"{self.base_url}{endpoint}"
        headers = kwargs.pop('headers', {})
        headers['Authorization'] = f'Bearer {token}'
        try:
            response = self.session.request(method=method, url=url, headers=headers, timeout=30, **kwargs)
            if response.status_code == 401:
                logger.warning("Got 401, refreshing token and retrying")
                self.token = None
                headers['Authorization'] = f'Bearer {self._get_token()}'
                response = self.session.request(method=method, url=url, headers=headers, timeout=30, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {method} {endpoint} - {str(e)}")
            raise Exception(f"Homebox API request failed: {str(e)}")

    @staticmethod
    def _items(response: Any) -> List[Dict[str, Any]]:
        """GET /v1/entities returns {items,page,pageSize,total}; /v1/tags returns a plain list."""
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            return response.get('items', []) or []
        return []

    # --- Entities (items and locations) ---------------------------------
    def search_items(self, query: str, include_archived: bool = False) -> List[Dict[str, Any]]:
        """Items matching a keyword (entities API returns items by default)."""
        params = {'q': query}
        if include_archived:
            params['includeArchived'] = 'true'
        return self._items(self._make_request('GET', '/api/v1/entities', params=params))

    def get_entity(self, entity_id: str) -> Dict[str, Any]:
        """Full detail for one item or location."""
        return self._make_request('GET', f'/api/v1/entities/{entity_id}')

    def list_locations(self) -> List[Dict[str, Any]]:
        """All location-type entities (each includes itemCount)."""
        return self._items(self._make_request('GET', '/api/v1/entities', params={'isLocation': 'true'}))

    def get_items_by_location(self, location_id: str) -> List[Dict[str, Any]]:
        """Items whose parent is the given location (replaces old ?locations=)."""
        return self._items(self._make_request('GET', '/api/v1/entities', params={'parentIds': [location_id]}))

    # --- Tags (formerly labels) -----------------------------------------
    def list_tags(self) -> List[Dict[str, Any]]:
        return self._items(self._make_request('GET', '/api/v1/tags'))

    def get_tag(self, tag_id: str) -> Dict[str, Any]:
        return self._make_request('GET', f'/api/v1/tags/{tag_id}')

    def get_items_by_tag(self, tag_id: str) -> List[Dict[str, Any]]:
        return self._items(self._make_request('GET', '/api/v1/entities', params={'tags': [tag_id]}))

    # --- Additional read-only endpoints (all GET) -----------------------
    def get_by_asset_id(self, asset_id: str) -> List[Dict[str, Any]]:
        """GET /v1/assets/{id} returns a paginated entity list."""
        return self._items(self._make_request('GET', f'/api/v1/assets/{asset_id}'))

    def get_path(self, entity_id: str) -> List[Dict[str, Any]]:
        """GET /v1/entities/{id}/path returns [{id,name,type}] from root to entity."""
        return self._items(self._make_request('GET', f'/api/v1/entities/{entity_id}/path'))

    def get_tree(self, with_items: bool) -> List[Dict[str, Any]]:
        params = {'withItems': 'true' if with_items else 'false'}
        return self._items(self._make_request('GET', '/api/v1/entities/tree', params=params))

    def list_maintenance(self, status: str) -> List[Dict[str, Any]]:
        return self._items(self._make_request('GET', '/api/v1/maintenance', params={'status': status}))

    def recent_items(self, order_by: str, limit: int) -> List[Dict[str, Any]]:
        """orderBy=createdAt/updatedAt sorts newest first (v0.26.2 repo_entities.go)."""
        params = {'orderBy': order_by, 'pageSize': str(limit), 'page': '1'}
        return self._items(self._make_request('GET', '/api/v1/entities', params=params))

    def item_maintenance(self, entity_id: str, status: str) -> List[Dict[str, Any]]:
        return self._items(self._make_request('GET', f'/api/v1/entities/{entity_id}/maintenance', params={'status': status}))

    def custom_field_names(self) -> List[str]:
        return self._items(self._make_request('GET', '/api/v1/entities/fields'))

    def custom_field_values(self, field: str) -> List[str]:
        return self._items(self._make_request('GET', '/api/v1/entities/fields/values', params={'field': field}))

    def items_by_custom_field(self, field: str, value: str) -> List[Dict[str, Any]]:
        return self._items(self._make_request('GET', '/api/v1/entities', params={'fields': [f"{field}={value}"]}))

    def purchase_value(self, start: str, end: str) -> Dict[str, Any]:
        params = {k: v for k, v in (('start', start), ('end', end)) if v}
        return self._make_request('GET', '/api/v1/groups/statistics/purchase-price', params=params)

    def statistics(self) -> Dict[str, Any]:
        return {
            "currency": self._make_request('GET', '/api/v1/currency'),
            "totals": self._make_request('GET', '/api/v1/groups/statistics'),
            "by_location": self._items(self._make_request('GET', '/api/v1/groups/statistics/locations')),
            "by_tag": self._items(self._make_request('GET', '/api/v1/groups/statistics/tags')),
        }


# --- Compact summaries: keep tool output small for local-model context ------
def _name_of(obj: Any) -> Any:
    return obj.get('name') if isinstance(obj, dict) else None


def summarize_entity(e: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "id": e.get("id"),
        "name": e.get("name"),
        "location": _name_of(e.get("parent")),
        "quantity": e.get("quantity"),
        "tags": [t.get("name") for t in (e.get("tags") or []) if isinstance(t, dict)],
    }
    if e.get("assetId"):
        out["assetId"] = e.get("assetId")
    if e.get("description"):
        out["description"] = e.get("description")[:200]
    return out


def summarize_location(e: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": e.get("id"),
        "name": e.get("name"),
        "parent": _name_of(e.get("parent")),
        "itemCount": e.get("itemCount"),
    }


def summarize_tag(t: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": t.get("id"), "name": t.get("name"), "description": t.get("description") or None}


# Initialize Homebox client from environment variables
HOMEBOX_URL = os.getenv("HOMEBOX_URL", "http://localhost:7745")
HOMEBOX_EMAIL = os.getenv("HOMEBOX_EMAIL")
HOMEBOX_PASSWORD = os.getenv("HOMEBOX_PASSWORD")

if not HOMEBOX_EMAIL or not HOMEBOX_PASSWORD:
    logger.error("HOMEBOX_EMAIL and HOMEBOX_PASSWORD environment variables are required")
    sys.exit(1)

homebox = HomeboxClient(HOMEBOX_URL, HOMEBOX_EMAIL, HOMEBOX_PASSWORD)

# Initialize FastMCP server
mcp = FastMCP("homebox-mcp")


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False)


@mcp.tool()
def search_homebox_items(query: str, include_archived: bool = False) -> str:
    """
    Search Homebox inventory items by keyword. Returns id, name, location, quantity and tags.

    Args:
        query: Search keyword or phrase
        include_archived: Also search archived items (default false)
    """
    try:
        items = homebox.search_items(query, include_archived)
        if not items:
            return f"No items found matching '{query}'"
        return _dump({"query": query, "count": len(items), "items": [summarize_entity(i) for i in items]})
    except Exception as e:
        logger.error(f"Error searching items: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def get_homebox_item_details(item_id: str) -> str:
    """
    Get full details of one Homebox item.

    Args:
        item_id: The UUID of the item (from search results)
    """
    try:
        return _dump(homebox.get_entity(item_id))
    except Exception as e:
        logger.error(f"Error getting item {item_id}: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def list_homebox_locations() -> str:
    """
    List all Homebox storage locations with their parent location and item count.
    """
    try:
        locations = homebox.list_locations()
        return _dump({"count": len(locations), "locations": [summarize_location(l) for l in locations]})
    except Exception as e:
        logger.error(f"Error listing locations: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def get_homebox_location_details(location_id: str) -> str:
    """
    Get full details of one Homebox location, including its sub-locations.

    Args:
        location_id: The UUID of the location (from list_homebox_locations)
    """
    try:
        return _dump(homebox.get_entity(location_id))
    except Exception as e:
        logger.error(f"Error getting location {location_id}: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def list_homebox_labels() -> str:
    """
    List all Homebox tags (called labels in older Homebox versions).
    """
    try:
        tags = homebox.list_tags()
        return _dump({"count": len(tags), "tags": [summarize_tag(t) for t in tags]})
    except Exception as e:
        logger.error(f"Error listing tags: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def get_homebox_label_details(label_id: str) -> str:
    """
    Get details of one Homebox tag (label).

    Args:
        label_id: The UUID of the tag (from list_homebox_labels)
    """
    try:
        return _dump(homebox.get_tag(label_id))
    except Exception as e:
        logger.error(f"Error getting tag {label_id}: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def get_items_in_location(location_id: str) -> str:
    """
    List the items stored directly in a Homebox location.

    Args:
        location_id: The UUID of the location (from list_homebox_locations)
    """
    try:
        items = homebox.get_items_by_location(location_id)
        return _dump({"location_id": location_id, "count": len(items), "items": [summarize_entity(i) for i in items]})
    except Exception as e:
        logger.error(f"Error getting items for location {location_id}: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def get_items_with_label(label_id: str) -> str:
    """
    List the Homebox items that have a specific tag (label).

    Args:
        label_id: The UUID of the tag (from list_homebox_labels)
    """
    try:
        items = homebox.get_items_by_tag(label_id)
        return _dump({"tag_id": label_id, "count": len(items), "items": [summarize_entity(i) for i in items]})
    except Exception as e:
        logger.error(f"Error getting items for tag {label_id}: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def get_item_attachments(item_id: str) -> str:
    """
    List the attachments of one Homebox item (manuals, warranties, receipts, photos).
    Link attachments include their URL, e.g. a link to the document in Paperless.

    Args:
        item_id: The UUID of the item (from search results)
    """
    try:
        entity = homebox.get_entity(item_id)
        out = []
        for a in entity.get("attachments") or []:
            row = {"title": a.get("title"), "type": a.get("type"), "primary": a.get("primary")}
            if a.get("mimeType") == "link/url":
                row["link"] = a.get("path")
            else:
                row["file"] = a.get("mimeType")
            out.append(row)
        return _dump({"item": entity.get("name"), "count": len(out), "attachments": out})
    except Exception as e:
        logger.error(f"Error getting attachments for {item_id}: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def get_item_by_asset_id(asset_id: str) -> str:
    """
    Find a Homebox item by its asset ID (the number printed on its label, e.g. 000-123).

    Args:
        asset_id: Asset ID, with or without dashes
    """
    try:
        items = homebox.get_by_asset_id(asset_id.strip())
        if not items:
            return f"No item found with asset ID '{asset_id}'"
        return _dump({"asset_id": asset_id, "count": len(items), "items": [summarize_entity(i) for i in items]})
    except Exception as e:
        logger.error(f"Error looking up asset {asset_id}: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def get_item_location_path(item_id: str) -> str:
    """
    Get where an item is stored as a full path, e.g. "Garage / Shelf 1 / Tote B-3 / Impact Driver".

    Args:
        item_id: The UUID of the item or location
    """
    try:
        path = homebox.get_path(item_id)
        names = [p.get("name") for p in path if isinstance(p, dict)]
        return _dump({"path": " / ".join(n for n in names if n), "levels": path})
    except Exception as e:
        logger.error(f"Error getting path for {item_id}: {str(e)}")
        return f"Error: {str(e)}"


def _render_tree(nodes: List[Dict[str, Any]], depth: int = 0, lines: List[str] = None) -> List[str]:
    lines = [] if lines is None else lines
    for n in nodes or []:
        marker = "" if n.get("type") == "location" else "- "
        lines.append(f"{'  ' * depth}{marker}{n.get('name')}  [{n.get('type')}, id={n.get('id')}]")
        _render_tree(n.get("children") or [], depth + 1, lines)
    return lines


@mcp.tool()
def get_location_tree(include_items: bool = False) -> str:
    """
    Show the whole Homebox location hierarchy as an indented outline.
    Set include_items=true to also list every item under each location (can be long).

    Args:
        include_items: Include items as well as locations (default false)
    """
    try:
        lines = _render_tree(homebox.get_tree(include_items))
        text = "\n".join(lines) if lines else "No locations found"
        if len(text) > 12000:
            text = text[:12000] + "\n... (truncated; ask about a specific location instead)"
        return text
    except Exception as e:
        logger.error(f"Error getting location tree: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def list_maintenance(status: str = "both") -> str:
    """
    List maintenance entries across all Homebox items.

    Args:
        status: "scheduled", "completed" or "both" (default "both")
    """
    try:
        status = status if status in ("scheduled", "completed", "both") else "both"
        entries = homebox.list_maintenance(status)
        rows = [{
            "item": e.get("itemName"),
            "item_id": e.get("itemID"),
            "task": e.get("name"),
            "scheduled": e.get("scheduledDate") or None,
            "completed": e.get("completedDate") or None,
            "cost": e.get("cost"),
        } for e in entries]
        return _dump({"status": status, "count": len(rows), "entries": rows})
    except Exception as e:
        logger.error(f"Error listing maintenance: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def get_inventory_statistics() -> str:
    """
    Get Homebox inventory totals: number of items, locations and tags, total value,
    items with warranty, plus totals per location and per tag.
    """
    try:
        return _dump(homebox.statistics())
    except Exception as e:
        logger.error(f"Error getting statistics: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def list_recent_items(limit: int = 10, sort: str = "added") -> str:
    """
    List the most recently added or updated Homebox items, newest first.

    Args:
        limit: Number of items to return (1-50, default 10)
        sort: "added" (by creation date) or "updated" (by last change); default "added"
    """
    try:
        limit = max(1, min(int(limit), 50))
        order_by = "updatedAt" if sort == "updated" else "createdAt"
        items = homebox.recent_items(order_by, limit)
        rows = []
        for i in items:
            r = summarize_entity(i)
            r["added"] = i.get("createdAt")
            r["updated"] = i.get("updatedAt")
            rows.append(r)
        return _dump({"sort": sort, "count": len(rows), "items": rows})
    except Exception as e:
        logger.error(f"Error listing recent items: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def get_item_maintenance(item_id: str, status: str = "both") -> str:
    """
    Get the maintenance history and scheduled maintenance for one Homebox item.

    Args:
        item_id: The UUID of the item
        status: "scheduled", "completed" or "both" (default "both")
    """
    try:
        status = status if status in ("scheduled", "completed", "both") else "both"
        entries = homebox.item_maintenance(item_id, status)
        rows = [{
            "task": e.get("name"),
            "description": (e.get("description") or "")[:200] or None,
            "scheduled": e.get("scheduledDate") or None,
            "completed": e.get("completedDate") or None,
            "cost": e.get("cost"),
        } for e in entries]
        return _dump({"item_id": item_id, "status": status, "count": len(rows), "entries": rows})
    except Exception as e:
        logger.error(f"Error getting maintenance for {item_id}: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def list_custom_fields(field: str = "") -> str:
    """
    List the custom field names used on Homebox items, or, if a field name is given,
    the distinct values stored in that field.

    Args:
        field: Optional custom field name to list values for
    """
    try:
        if field:
            values = homebox.custom_field_values(field)
            return _dump({"field": field, "count": len(values), "values": values})
        names = homebox.custom_field_names()
        return _dump({"count": len(names), "fields": names})
    except Exception as e:
        logger.error(f"Error listing custom fields: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def find_items_by_custom_field(field: str, value: str) -> str:
    """
    Find Homebox items whose custom field has a given value (exact field name from list_custom_fields).

    Args:
        field: Custom field name
        value: Value to match
    """
    try:
        items = homebox.items_by_custom_field(field, value)
        return _dump({"field": field, "value": value, "count": len(items), "items": [summarize_entity(i) for i in items]})
    except Exception as e:
        logger.error(f"Error finding items by field {field}: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
def get_purchase_value_over_time(start: str = "", end: str = "") -> str:
    """
    Get the total purchase value of the inventory over a date range (useful for insurance).
    Homebox defaults to the last month if no dates are given.

    Args:
        start: Start date YYYY-MM-DD (optional)
        end: End date YYYY-MM-DD (optional)
    """
    try:
        return _dump(homebox.purchase_value(start, end))
    except Exception as e:
        logger.error(f"Error getting purchase value: {str(e)}")
        return f"Error: {str(e)}"


if __name__ == "__main__":
    SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT = int(os.getenv("SERVER_PORT", "8031"))
    logger.info(f"Homebox MCP Server starting with HOMEBOX_URL={HOMEBOX_URL}")
    logger.info(f"Starting HTTP server on {SERVER_HOST}:{SERVER_PORT}")
    mcp.run(transport="streamable-http", host=SERVER_HOST, port=SERVER_PORT)
