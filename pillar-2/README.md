# Rheinbahn Live Map Prototype (`solution2`)

A lightweight prototype web app for visualizing local transit conditions around Dusseldorf.

It includes:
- Interactive map with transit stops
- Incident display and incident reporting
- Login with role-based dashboard visibility (`user` vs `admin`)
- Route calculation with accident-aware detour logic
- Static frontend served by a minimal Node.js HTTP server

## Quick Start

1. Open a terminal in this folder:
   ```powershell
   cd C:\Users\sahil\Downloads\zukunftDusseldorf\solution2
   ```
2. Start the server:
   ```powershell
   npm start
   ```
3. Open in browser:
   - [http://localhost:3000](http://localhost:3000)

The app starts from the `start` script in `package.json`:
```json
"start": "node server.js"
```

## Demo Login Credentials

Configured in `app.js`:
- `user / user123` (regular user)
- `user2 / user234` (regular user)
- `admin / admin123` (admin)

## Tech Stack

- Node.js runtime (for static file serving)
- Plain HTML/CSS/JavaScript (no framework, no build step)
- [Leaflet](https://leafletjs.com/) for map rendering
- [Leaflet Routing Machine](https://www.liedman.net/leaflet-routing-machine/) for route display
- OpenStreetMap tile layer
- Nominatim geocoding API (address lookup)
- OSRM route engine via Leaflet Routing Machine

## Project Structure

```text
solution2/
|- app.js                # Main frontend logic (map, auth, incidents, reporting, routing)
|- index.html            # Main UI skeleton and external library includes
|- styles.css            # App styling and responsive layout
|- server.js             # Minimal Node HTTP static server
|- package.json          # Project metadata + npm scripts
|- dispatch-log.ndjson   # Legacy/reference dispatch snapshots (not actively consumed by current app)
```

## How the App Works

### 1. Server Layer (`server.js`)
- Runs an HTTP server (default port `3000`, configurable via `PORT` env var).
- Serves static files from project root.
- Maps `/` to `index.html`.
- Uses MIME-type mapping for html/js/css/json/images.
- Includes path normalization/safety check to block path traversal.

### 2. UI Layer (`index.html` + `styles.css`)
- Landing/home section with login prompt.
- Dashboard split into:
  - Left: map
  - Right: operational sidebar panels
- Modal login form.
- Responsive behavior for smaller screens.

### 3. Application Logic (`app.js`)
- Defines static stop data (`STOPS`) and seeded incidents (`INCIDENTS`).
- Builds Leaflet map and renders stop markers.
- Handles login/logout and role-specific UI visibility.
- Supports manual incident reports from users.
- Adds route search between stops or geocoded addresses.
- Detects route overlap with severe accident incidents and calculates a detour waypoint.
- Shows impacted stops and estimated extra travel minutes.

## Role Behavior

- Logged out:
  - Sees home page only.
- Logged in as `user`:
  - Main dashboard visible.
  - AI learning panel and employee panel are hidden.
- Logged in as `admin`:
  - Full dashboard including AI and employee operational panels.

## Setup on Another Computer

## Prerequisites
- Node.js 18+ recommended (Node 16+ should also work for this prototype)
- npm (bundled with Node.js)
- Internet access (for CDN libraries, OSM tiles, geocoding, and routing)

## Steps

1. Copy or clone project folder.
2. Open terminal in project root.
3. (Optional) install dependencies:
   ```bash
   npm install
   ```
   Note: this project currently has no npm dependencies, so install is usually a no-op.
4. Start app:
   ```bash
   npm start
   ```
5. Open `http://localhost:3000` in browser.

## Running on a Different Port

- Windows PowerShell:
  ```powershell
  $env:PORT=8080
  npm start
  ```
- macOS/Linux:
  ```bash
  PORT=8080 npm start
  ```

Then open `http://localhost:8080`.

## Troubleshooting

- Port already in use:
  - Change `PORT` value (example above).
- Map loads but route/address search fails:
  - Check internet connectivity (Nominatim/OSRM endpoints are external).
- Blank page or missing styling/script:
  - Confirm all files are in same folder and server started from project root.
- Login fails:
  - Use exact demo credentials listed above.

## Notes and Limitations

- This is a prototype with in-memory state (`state` object). Data resets on page refresh.
- Incident reports are not persisted to a backend/database.
- `dispatch-log.ndjson` exists for historical/legacy data context and is not currently wired into runtime behavior.
- Credentials are hardcoded for demo use only (not production-safe).

## Possible Next Improvements

- Add persistent backend storage for reports/incidents.
- Move hardcoded credentials to secure auth service.
- Replace seeded data with real-time transport feeds.
- Add automated tests for routing and UI state logic.
- Containerize with Docker for consistent deployment.
