# EchoStream

> **Turn your TikTok LIVE events into real-time audio.**

EchoStream is a real-time TikTok LIVE text-to-speech and event alert platform designed for streamers. It connects to a TikTok LIVE stream, receives events such as comments, likes, follows, and gifts, then processes those events according to each user's preferences.

The platform supports text-to-speech, custom audio alerts, and system sounds, with configurable global event preferences and per-gift overrides.

---

## ✨ Features

### TikTok LIVE Integration

EchoStream connects to TikTok LIVE streams and receives real-time events, including:

* 💬 Comments
* ❤️ Likes
* 👤 Follows
* 🎁 Gifts
* Other supported LIVE events

The LIVE event connection is handled using the existing TikTok LIVE client integration and Euler Stream signing infrastructure.

---

## 🔊 Text-to-Speech

EchoStream can convert incoming LIVE events into speech.

Examples:

```text
John said: Hello everyone!
```

```text
Jane followed the stream!
```

```text
Peter sent a Rose!
```

Users can configure how events are handled and choose whether an event should trigger:

* **Text-to-Speech**
* **Custom audio**
* **System sound**

---

## ⚙️ Event Preferences

Each user has configurable event preferences.

The preferences API provides a central configuration for events such as:

```json
{
  "events": {
    "like": {},
    "follow": {},
    "gift": {}
  }
}
```

Each event can be independently configured.

For example:

```text
Follow
├── Enabled
├── Alert type
│   ├── TTS
│   ├── Custom sound
│   └── System sound
├── TTS settings
└── Audio settings
```

The same model applies to:

```text
Like
Follow
Gift
```

This avoids duplicating event-specific preference fields throughout the main user preferences model.

---

## 🎁 Gift Catalog

EchoStream maintains its own TikTok gift catalog.

The gift catalog is designed to work independently of whether a user is currently connected to a TikTok LIVE stream.

The general flow is:

```text
TikTok / Gift Source
        ↓
Catalog Sync Worker
        ↓
EchoStream Database
        ↓
GET /v1/gifts
        ↓
Frontend Gift Picker
```

This allows users to configure gift preferences before going live.

For example, a user can select:

```text
Rose
Lion
TikTok Universe
...
```

and configure a specific action for each gift.

The frontend does not need to connect to TikTok LIVE to discover available gifts.

---

## 🔄 Gift Catalog Synchronization

EchoStream uses a synchronized database catalog instead of fetching gifts from an external provider directly in the request path.

This means:

```text
GET /v1/gifts
```

reads from EchoStream's database.

It does **not** depend on a third-party provider being available during every frontend request.

The synchronization process:

1. Fetches the gift catalog from the configured source.
2. Validates the full synchronization.
3. Creates new gifts.
4. Updates existing gifts.
5. Marks gifts no longer present as inactive only after a successful complete synchronization.
6. Preserves the previous catalog if synchronization fails.

The catalog can contain information such as:

```text
Gift ID
Name
Image
Cost
Status
Metadata
```

Inactive gifts can be hidden from new selections while still allowing existing user preferences to resolve correctly.

---

## 🎯 Per-Gift Preferences

EchoStream supports global gift preferences and individual gift overrides.

The resolution model is:

```text
Incoming Gift
      ↓
Does this gift have an override?
      │
   Yes ─────────────→ Use gift-specific preference
      │
      No
      ↓
Use global gift preference
```

For example:

```text
Global Gift Preference
└── TTS

Rose
└── Custom Sound Override

Lion
└── System Sound Override
```

This allows streamers to create custom experiences without configuring every gift individually.

---

## 🗣️ TTS Providers

EchoStream supports multiple text-to-speech providers and is designed to support provider-specific capabilities.

The architecture supports:

* Microsoft Edge TTS
* Fish Audio
* Additional providers in the future

Different providers can expose different voices and capabilities.

Provider-specific configuration is handled without exposing one user's private resources to another user.

---

## 🎙️ Voice Selection and Cloning

Where supported by the configured provider and subscription plan, EchoStream can support:

* Voice selection
* Provider-specific voices
* Custom/cloned voices
* Private user-owned voices

User-owned voices are intended to remain isolated from other users.

A user's private voice should not appear in another user's voice selection.

---

## 💬 Comment Processing

Incoming comments can pass through configurable processing before being sent to TTS.

Possible preferences include:

* Maximum message length
* Profanity filtering
* Emoji conversion
* Command prefix requirements
* Allowed user groups
* Spam protection
* Repeated message handling
* Request limits

The general processing flow is:

```text
TikTok Comment
      ↓
Event Received
      ↓
Preference Lookup
      ↓
Filter / Validation
      ↓
Spam Protection
      ↓
Queue
      ↓
TTS Generation
      ↓
Audio Output
```

---

## ❤️ Like Events

TikTok likes can arrive in high volumes.

EchoStream is designed to avoid treating every individual like as a separate expensive TTS operation.

Like events can be merged or aggregated before alert processing.

Conceptually:

```text
100 individual likes
        ↓
Aggregation
        ↓
One meaningful alert
```

This helps protect the event and TTS pipeline from unnecessary load.

---

## 📦 Event Processing Pipeline

The real-time event pipeline follows this general structure:

```text
TikTok LIVE
    ↓
TikTok LIVE Client
    ↓
Real-Time Event Handler
    ↓
Event Normalization
    ↓
User Preferences
    ↓
Event Filtering
    ↓
Spam Protection
    ↓
Event Queue
    ↓
TTS / Audio Processing
    ↓
WebSocket
    ↓
Client Application
```

EchoStream separates incoming event handling from slower operations such as database access and TTS generation where possible.

This is important because a slow database query or external API request should not unnecessarily block the LIVE event pipeline.

---

# 🔌 Euler Stream Integration

EchoStream uses Euler Stream infrastructure as part of its TikTok LIVE connection ecosystem.

Euler Stream is used for distinct workloads.

## LIVE Event Connection

The existing LIVE event implementation uses the current signing/client flow.

The connection process is conceptually:

```text
EchoStream
    ↓
TikTok LIVE Client
    ↓
Euler Stream Signing Infrastructure
    ↓
TikTok LIVE WebSocket
    ↓
Persistent Event Stream
```

After the connection is established, events such as:

```text
Comments
Likes
Follows
Gifts
```

arrive through the persistent event connection.

They are not treated as a separate Euler API request for every incoming event.

---

## Gift Catalog API

The gift catalog synchronization uses a dedicated Euler API configuration.

This is intentionally separate from the existing LIVE event implementation.

```text
Existing TikTok LIVE Connection
        ↓
Unchanged

Gift Catalog Synchronization
        ↓
Dedicated Euler API Configuration
        ↓
Gift Catalog Database
```

Keeping these workloads separate reduces the risk of unintentionally changing a working LIVE connection implementation while adding gift catalog functionality.

---

# 🔐 Authentication

EchoStream uses JWT-based authentication with refresh tokens and per-session authentication.

The system supports multiple devices independently.

For example:

```text
User

├── Laptop
│   └── Session A
│       ├── Access Token A
│       └── Refresh Token A
│
└── Phone
    └── Session B
        ├── Access Token B
        └── Refresh Token B
```

Each login creates an independent session.

---

## Per-Session Logout

Logging out from one device should not log the user out from every device.

For example:

```text
Device A → Logged in
Device B → Logged in

Logout Device B

Device A → Still logged in ✅
Device B → Logged out ❌
```

EchoStream achieves this through session-based authentication.

Each session has its own identifier:

```text
session_id
```

The session ID is associated with:

* The user
* The access token
* The refresh token

When a user logs out:

```text
Current Session
      ↓
Revoked
      ↓
Access Token Invalid
Refresh Token Invalid
```

Other sessions belonging to the same user remain active.

---

## User Sessions

The database contains a dedicated session model conceptually structured as:

```text
UserSession
├── id
├── user_id
├── created_at
├── last_used_at
└── revoked_at
```

Refresh tokens are associated with sessions.

This provides a clean foundation for future features such as:

* Device management
* Active session lists
* Logout from individual devices
* Logout from all devices
* Suspicious session detection
* Session expiration policies

---

## Refresh Token Rotation

Refresh tokens are handled independently from access tokens.

When a refresh occurs, the user remains associated with the same session.

Conceptually:

```text
Session A
    ↓
Old Refresh Token
    ↓
Refresh
    ↓
New Refresh Token
    ↓
Still Session A
```

Refreshing a token does not unintentionally create a new device session.

---

# 💳 Subscription Access

EchoStream is designed around subscription-based feature access.

The general user flow is:

```text
Create Account
      ↓
Authenticate
      ↓
Subscribe / Pay
      ↓
Subscription Activated
      ↓
Access Paid Features
      ↓
Configure Preferences
      ↓
Start LIVE
```

Subscription status can control access to premium functionality such as:

* Advanced TTS providers
* Voice cloning
* Advanced spam protection
* Additional preferences
* Premium event controls
* Higher usage limits

---

# 🔗 REST API

The API is built around versioned endpoints.

Example structure:

```text
/v1/
├── auth
├── preferences
├── gifts
├── tts
├── live
└── other services
```

---

## Preferences

### Get Preferences

```http
GET /v1/preferences
```

Returns the user's preferences, including event-specific configuration.

Conceptually:

```json
{
  "selected_voice": "example",
  "volume": 100,
  "speed": 100,
  "pitch": 0,

  "events": {
    "like": {},
    "follow": {},
    "gift": {}
  }
}
```

---

### Update Preferences

```http
PUT /v1/preferences
```

Updates user preferences, including event configurations.

The frontend should be able to update global preferences and event-specific preferences through the same preferences model.

---

## Gift Catalog

```http
GET /v1/gifts
```

Returns the locally stored TikTok gift catalog.

The frontend can use this endpoint to populate the gift picker:

```text
Settings
    ↓
Gift Preferences
    ↓
GET /v1/gifts
    ↓
Display Gift List
    ↓
User Selects Gift
    ↓
Configure Override
```

This works whether or not the user is currently LIVE.

---

## LIVE Control

EchoStream includes LIVE control endpoints for managing a user's streaming session.

Conceptually:

```http
POST /v1/live/start
```

and:

```http
POST /v1/live/stop
```

The exact implementation manages the lifecycle of the user's TikTok LIVE connection.

---

## Text-to-Speech

EchoStream exposes TTS functionality through the API and real-time WebSocket pipeline.

Conceptually:

```text
Text
 ↓
TTS Provider Selection
 ↓
Voice Resolution
 ↓
Speech Generation
 ↓
Audio Output
```

---

## Logout

The logout endpoint revokes only the currently authenticated session.

```http
POST /logout
```

Example:

```http
Authorization: Bearer <access_token>
```

After logout:

```text
Current device session → revoked
Current access token   → invalid
Current refresh token  → invalid

Other devices          → unaffected
```

---

# 🔌 WebSockets

EchoStream uses WebSockets for real-time communication.

The WebSocket layer is responsible for real-time workflows such as:

* Live TTS communication
* Event processing
* Audio-related messages
* LIVE status updates

The architecture avoids unnecessary synchronous database work inside asynchronous event handlers.

Blocking synchronous database operations inside an async event loop can prevent other LIVE streams from being processed efficiently.

The goal is:

```text
Async Event
    ↓
Non-blocking Processing
    ↓
Async / Isolated Database Work
    ↓
Queue
    ↓
TTS Processing
```

---

# 🗄️ Database

EchoStream uses SQLAlchemy models and Alembic for schema management.

Alembic migrations are part of the repository and should always be committed.

The migration history is required for environments such as:

```text
Development
    ↓
Staging
    ↓
Production
```

Each environment should be able to upgrade its database using:

```bash
alembic upgrade head
```

---

## Migration Workflow

Check the current revision:

```bash
alembic current
```

Check all migration heads:

```bash
alembic heads
```

View migration history:

```bash
alembic history --verbose
```

Upgrade:

```bash
alembic upgrade head
```

### Important

A healthy merged migration history should normally result in one final Alembic head.

If multiple heads exist:

```text
Revision A (head)
Revision B (head)
```

Alembic may require a merge revision.

A merge migration joins the histories:

```text
Head A ──┐
         ├── Merge Revision
Head B ──┘
```

Migration files belong in Git:

```text
alembic/
├── env.py
└── versions/
    ├── ...
    └── migration_files.py
```

Do not ignore the Alembic migration history.

---

# 🏗️ Architecture

EchoStream is currently designed as a practical application architecture suitable for development and early production.

Conceptually:

```text
                     ┌─────────────────────┐
                     │     EchoStream      │
                     │      Backend        │
                     └──────────┬──────────┘
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
       REST API           WebSockets         Background Work
             │                  │                  │
             └──────────────────┼──────────────────┘
                                │
                                ▼
                       LIVE Event Pipeline
                                │
                 ┌──────────────┼──────────────┐
                 │              │              │
                 ▼              ▼              ▼
              Comments        Gifts          Follows
                 │              │              │
                 └──────────────┼──────────────┘
                                ▼
                           Preferences
                                │
                                ▼
                              Queue
                                │
                                ▼
                               TTS
```

As the platform grows, expensive components can be separated into dedicated workers.

Possible future architecture:

```text
                        API Server
                            │
                ┌───────────┼───────────┐
                ▼           ▼           ▼
          LIVE Worker    LIVE Worker   LIVE Worker
                │           │           │
                └───────────┼───────────┘
                            ▼
                       Event Queue
                            ▼
                      TTS Workers
```

There is no need to prematurely introduce this complexity before real load requires it.

---

# 📈 Scaling Considerations

The number of concurrent TikTok LIVE streamers is not determined only by the TikTok connection provider.

EchoStream capacity depends on:

```text
TikTok Connection Stability
        +
Concurrent LIVE Connections
        +
Events Per Second
        +
Database Performance
        +
Preference Processing
        +
Queue Capacity
        +
TTS Provider Throughput
        +
Server CPU / RAM
```

A persistent LIVE connection may receive a large number of events without requiring a new signing request for every event.

However, reconnects can require additional connection/signing activity.

At scale, likely bottlenecks include:

* TTS generation
* Queue growth
* High-volume comment streams
* Database access
* CPU usage
* Memory usage
* WebSocket connection management

Monitoring should eventually include:

```text
Active Streams
Active WebSockets
Events / Second
Comments / Second
TTS Queue Depth
TTS Latency
Failed TTS Requests
Reconnect Count
Database Latency
CPU Usage
Memory Usage
```

---

# 🧪 Development

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure environment variables:

```bash
cp .env.example .env
```

Update the required environment values.

Run database migrations:

```bash
alembic upgrade head
```

Start the application using the project's configured development command.

---

# 🔑 Environment Variables

EchoStream uses environment variables for configuration.

Depending on the deployment and enabled features, configuration may include:

```text
DATABASE_URL
JWT_SECRET_KEY

ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS

TTS_PROVIDER_CONFIGURATION

FISH_AUDIO_CONFIGURATION

EULER_GIFT_CATALOG_API_KEY

R2_CONFIGURATION

OTHER_PROVIDER_CREDENTIALS
```

Never commit secrets.

The following should generally remain outside Git:

```text
.env
.env.local
private credentials
API secrets
database passwords
```

---

# 🧪 Recommended Testing

Before deployment, test the complete flow.

## Authentication

```text
Register
   ↓
Login
   ↓
Authenticated Request
   ↓
Refresh Token
   ↓
Logout
   ↓
Verify Session Is Revoked
```

---

## Multi-Device Logout

Test using two separate sessions.

```text
Device A Login
      ↓
Session A

Device B Login
      ↓
Session B
```

Then:

```text
Logout Device B
```

Expected:

```text
Device A → authenticated ✅
Device B → unauthorized ❌
```

Also verify:

```text
Device A refresh → works
Device B refresh → fails
```

---

## Preferences

Test:

```text
GET /v1/preferences
```

Verify:

```text
General Preferences
Events
├── Like
├── Follow
└── Gift
```

Then update:

```text
Like Preference
Follow Preference
Gift Preference
```

and confirm the event pipeline uses the updated configuration.

---

## Gift Catalog

Test:

```text
Catalog Sync
      ↓
Database Updated
      ↓
GET /v1/gifts
      ↓
Frontend Receives Gifts
```

Also test provider failure:

```text
Provider Unavailable
      ↓
Sync Fails
      ↓
Existing Catalog Preserved
```

A failed or partial synchronization should not destroy a previously successful catalog.

---

## LIVE Events

Test a TikTok LIVE session and verify:

```text
Comments
Likes
Follows
Gifts
```

Confirm each event:

1. Reaches EchoStream.
2. Resolves the user's preferences.
3. Applies filtering.
4. Uses the correct event configuration.
5. Enters the correct queue.
6. Produces the expected TTS or audio alert.

---

# 🚀 Production Checklist

Before production deployment:

* [ ] Database migrations are committed.
* [ ] Alembic has one intended migration head.
* [ ] `alembic upgrade head` succeeds.
* [ ] Environment secrets are configured.
* [ ] `.env` is not committed.
* [ ] Authentication is tested.
* [ ] Multi-device sessions are tested.
* [ ] Logout revokes only the current session.
* [ ] Refresh token rotation is tested.
* [ ] Preferences are tested.
* [ ] Event preferences are tested.
* [ ] Gift catalog synchronization is tested.
* [ ] Failed catalog synchronization preserves existing data.
* [ ] LIVE start and stop are tested.
* [ ] Comments are tested.
* [ ] Likes are tested.
* [ ] Follows are tested.
* [ ] Gifts are tested.
* [ ] TTS providers are tested.
* [ ] Queue behavior is tested.
* [ ] WebSocket reconnect behavior is tested.
* [ ] Logging and error reporting are configured.
* [ ] Database backups are configured.

---

# 🛣️ Future Improvements

Potential future improvements include:

* Device/session management UI
* Logout from all devices
* Active session listing
* Admin gift catalog synchronization
* Manual catalog refresh
* Catalog freshness monitoring
* ETag support for gift catalog responses
* Dedicated LIVE workers
* Dedicated TTS workers
* Distributed event queues
* Horizontal scaling
* Stream-level analytics
* Usage analytics
* Improved monitoring and observability
* Additional streaming platforms
* Additional TTS providers
* More advanced spam protection

---

# 📄 Project Philosophy

EchoStream is being built around a few important principles:

### Keep the MVP practical

Do not build a massive distributed architecture before real traffic requires it.

### Separate real-time and slow work

LIVE event handling should remain responsive even when slower operations are happening.

### Store important external data locally

The gift catalog should not depend on an external provider for every frontend request.

### Keep user sessions independent

Logging out from one device should not affect another device.

### Prefer overrides over duplication

Global preferences should provide defaults, while event-specific and gift-specific preferences override them when necessary.

### Scale based on measurements

Measure:

```text
CPU
Memory
Events
Queue Depth
TTS Latency
Database Performance
```

before redesigning the architecture.

---

## License

License information can be added here.

---

## Contributing

Contributions, improvements, bug reports, and discussions are welcome.

Before submitting changes:

1. Keep the working tree clean.
2. Run relevant tests.
3. Add migrations for schema changes.
4. Verify Alembic migration history.
5. Avoid committing secrets.
6. Keep LIVE event handling non-blocking where possible.

---

**EchoStream — bringing TikTok LIVE events to life through real-time audio.**

