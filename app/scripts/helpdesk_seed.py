CATEGORIES = [
    {
        "slug": "getting-started",
        "title": "Getting Started",
        "description": "Learn the basics and get EchoStream ready for your first stream.",
        "icon": "rocket",
        "sort_order": 0,
    },
    {
        "slug": "live-runtime",
        "title": "Live Runtime",
        "description": "Everything about connecting EchoStream to your TikTok LIVE and keeping the runtime running.",
        "icon": "radio",
        "sort_order": 1,
    },
    {
        "slug": "alerts",
        "title": "Alerts & TTS",
        "description": "Configure LIVE events, alerts, text-to-speech and alert behavior.",
        "icon": "notifications",
        "sort_order": 2,
    },
    {
        "slug": "voices",
        "title": "Voices & Text-to-Speech",
        "description": "Choose voices and configure the speech used by EchoStream.",
        "icon": "volume-high",
        "sort_order": 3,
    },
    {
        "slug": "voice-cloning",
        "title": "Voice Cloning",
        "description": "Create, preview and manage custom voices.",
        "icon": "mic",
        "sort_order": 4,
    },
    {
        "slug": "sounds",
        "title": "Custom Sounds",
        "description": "Upload and manage custom audio for your alerts.",
        "icon": "musical-notes",
        "sort_order": 5,
    },
    {
        "slug": "plans-billing",
        "title": "Plans & Billing",
        "description": "Understand EchoStream plans, payments and subscription management.",
        "icon": "card",
        "sort_order": 6,
    },
    {
        "slug": "account-settings",
        "title": "Account & Settings",
        "description": "Manage your account, preferences and notification settings.",
        "icon": "settings",
        "sort_order": 7,
    },
    {
        "slug": "troubleshooting",
        "title": "Troubleshooting",
        "description": "Find solutions to common EchoStream issues.",
        "icon": "construct",
        "sort_order": 8,
    },
]




ARTICLES = [
    # =========================================================
    # GETTING STARTED
    # =========================================================

    {
        "category": "getting-started",
        "slug": "what-is-echostream",
        "title": "What is EchoStream?",
        "excerpt": "Learn what EchoStream does and how it enhances your TikTok LIVE streams.",
        "content": """
EchoStream is a real-time AI assistant for TikTok LIVE.

It connects to your TikTok LIVE session and can respond to events such as
comments, gifts, follows and likes using text-to-speech and configurable
alerts.

You can customize how EchoStream responds, choose different TTS voices,
configure alerts, use custom sounds and, on supported plans, use voice
cloning.

EchoStream runs alongside your LIVE session so you can automate audience
interactions without manually responding to every event.
""".strip(),
        "icon": "information-circle",
        "tags": ["echostream", "overview", "getting-started"],
        "search_keywords": "what is EchoStream what does EchoStream do TikTok LIVE AI assistant",
        "sort_order": 0,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "getting-started",
        "slug": "getting-started-with-echostream",
        "title": "How do I get started with EchoStream?",
        "excerpt": "Follow the basic steps to get EchoStream ready for your first stream.",
        "content": """
Create or sign in to your EchoStream account, configure your preferences,
connect your TikTok LIVE username and start the Live Runtime.

Once the runtime connects successfully, EchoStream can begin receiving
supported LIVE events.

Before going live, it is a good idea to configure your alert preferences,
choose your TTS voice and test your audio settings.
""".strip(),
        "icon": "rocket",
        "tags": ["getting-started", "setup", "first-stream"],
        "search_keywords": "start EchoStream setup first stream getting started configure account",
        "sort_order": 1,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "getting-started",
        "slug": "what-do-i-need-to-use-echostream",
        "title": "What do I need to use EchoStream?",
        "excerpt": "See what you need before using EchoStream during a TikTok LIVE.",
        "content": """
You need an EchoStream account and a TikTok account that you can use for
LIVE streaming.

You also need a supported device with the EchoStream app installed and an
internet connection.

For TTS and audio alerts, make sure your device's audio output is configured
correctly and that your volume is turned up.

Some EchoStream features depend on your subscription plan.
""".strip(),
        "icon": "checkmark-circle",
        "tags": ["getting-started", "requirements", "setup"],
        "search_keywords": "requirements device internet TikTok account EchoStream setup",
        "sort_order": 2,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # LIVE RUNTIME
    # =========================================================

    {
        "category": "live-runtime",
        "slug": "connect-echostream-to-tiktok",
        "title": "How do I connect EchoStream to TikTok?",
        "excerpt": "Connect EchoStream to your TikTok LIVE session using your TikTok username.",
        "content": """
Open the Live Runtime section in EchoStream and enter the TikTok username
for the account you want to monitor.

Start the runtime and wait for EchoStream to establish the connection.

Once connected, EchoStream can receive supported events from the LIVE
session and process them according to your configured preferences.
""".strip(),
        "icon": "logo-tiktok",
        "tags": ["tiktok", "live", "runtime", "connection"],
        "search_keywords": "connect TikTok TikTok LIVE username runtime start connection",
        "sort_order": 0,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "live-runtime",
        "slug": "what-is-live-runtime",
        "title": "What is the Live Runtime?",
        "excerpt": "Understand what the Live Runtime does while you are streaming.",
        "content": """
The Live Runtime is the part of EchoStream that maintains the connection
to your TikTok LIVE session.

While the runtime is active, EchoStream listens for supported LIVE events
and processes them according to your alert and TTS preferences.

You can start or stop the runtime from the Live Runtime section of the app.
""".strip(),
        "icon": "radio",
        "tags": ["runtime", "live", "tiktok"],
        "search_keywords": "Live Runtime runtime meaning what does runtime do",
        "sort_order": 1,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "live-runtime",
        "slug": "does-echostream-need-to-stay-running",
        "title": "Does EchoStream need to stay running during my LIVE?",
        "excerpt": "Understand when the EchoStream runtime needs to be active.",
        "content": """
Yes. The Live Runtime needs to remain active while you want EchoStream to
process events from your TikTok LIVE.

If the runtime is stopped or disconnected, EchoStream cannot receive and
process new LIVE events until the connection is restored.
""".strip(),
        "icon": "play-circle",
        "tags": ["runtime", "live", "connection"],
        "search_keywords": "runtime running live stay connected EchoStream TikTok",
        "sort_order": 2,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "live-runtime",
        "slug": "why-is-my-tiktok-runtime-disconnected",
        "title": "Why is my TikTok runtime disconnected?",
        "excerpt": "Learn what can cause the Live Runtime to disconnect.",
        "content": """
A runtime connection can be interrupted by network problems, a TikTok
connection issue, the LIVE session ending or an unexpected runtime error.

Check your internet connection first and verify that the TikTok username
configured in EchoStream is correct.

If the problem continues, stop the runtime and start it again. If you
continue to experience connection problems, check the Troubleshooting
section or contact support.
""".strip(),
        "icon": "cloud-offline",
        "tags": ["runtime", "disconnect", "tiktok", "troubleshooting"],
        "search_keywords": "TikTok runtime disconnected connection lost offline runtime error",
        "sort_order": 3,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # ALERTS & TTS
    # =========================================================

    {
        "category": "alerts",
        "slug": "what-are-echostream-alerts",
        "title": "What are EchoStream alerts?",
        "excerpt": "Learn how EchoStream responds to events during your TikTok LIVE.",
        "content": """
EchoStream alerts allow the app to react when specific events occur
during your TikTok LIVE.

Depending on your configuration, events such as gifts, follows and likes
can trigger text-to-speech or other alert behavior.

Each alert can be configured independently from the alert preferences.
""".strip(),
        "icon": "notifications",
        "tags": ["alerts", "events", "tts"],
        "search_keywords": "alerts TikTok gifts follows likes events EchoStream",
        "sort_order": 0,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "configure-gift-alerts",
        "title": "How do I configure gift alerts?",
        "excerpt": "Choose which TikTok gifts should trigger EchoStream alerts.",
        "content": """
Open the Gift Alerts section to configure individual TikTok gift alerts.

You can search for a gift and enable or disable its alert behavior.
Supported configurations can include TTS and custom audio depending on
your plan and settings.

Gift alerts are configured separately from the general LIVE event
preferences.
""".strip(),
        "icon": "gift",
        "tags": ["alerts", "gifts", "tiktok", "tts"],
        "search_keywords": "gift alerts configure gifts TikTok gift TTS enable disable",
        "sort_order": 1,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "configure-like-follow-alerts",
        "title": "Can EchoStream respond to likes and follows?",
        "excerpt": "Configure EchoStream to respond to supported LIVE engagement events.",
        "content": """
EchoStream supports configurable alerts for supported TikTok LIVE events,
including likes and follows.

You can enable or disable these event types from your alert preferences
and configure the TTS behavior associated with them.
""".strip(),
        "icon": "heart",
        "tags": ["alerts", "likes", "follows", "events"],
        "search_keywords": "like follow alerts TikTok likes follows engagement",
        "sort_order": 2,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "customize-alert-text",
        "title": "How do I customize what EchoStream says?",
        "excerpt": "Customize the text EchoStream uses when speaking an alert.",
        "content": """
EchoStream uses alert templates to determine what is spoken for supported
events.

Templates can contain dynamic event information such as the user's name
and the event that triggered the alert.

For example, a template can use the user's name and event information to
produce a message such as a viewer sending a gift.

Available template tokens depend on the specific alert type.
""".strip(),
        "icon": "create",
        "tags": ["alerts", "templates", "tts", "customization"],
        "search_keywords": "custom alert text template tokens user event TTS message",
        "sort_order": 3,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "alert-queue",
        "title": "How does the alert queue work?",
        "excerpt": "Understand how EchoStream handles multiple alerts arriving close together.",
        "content": """
When multiple supported events arrive close together, EchoStream can
process them through its alert queue.

The queue helps prevent several audio alerts from attempting to play
simultaneously.

Queue behavior and available limits depend on your EchoStream plan and
alert configuration.
""".strip(),
        "icon": "list",
        "tags": ["alerts", "queue", "tts"],
        "search_keywords": "alert queue multiple alerts audio queue TTS",
        "sort_order": 4,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # VOICES & TTS
    # =========================================================

    {
        "category": "voices",
        "slug": "how-text-to-speech-works",
        "title": "How does EchoStream text-to-speech work?",
        "excerpt": "Understand how EchoStream turns LIVE events into spoken audio.",
        "content": """
When an enabled event occurs, EchoStream generates the configured alert
text and sends it through the selected text-to-speech provider.

The resulting audio is then played through your configured audio output.

Your selected provider and voice determine how the generated speech sounds.
""".strip(),
        "icon": "volume-high",
        "tags": ["tts", "text-to-speech", "audio"],
        "search_keywords": "TTS text to speech how does EchoStream voice audio work",
        "sort_order": 0,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "voices",
        "slug": "change-tts-voice",
        "title": "How do I change the TTS voice?",
        "excerpt": "Choose a different voice for EchoStream's text-to-speech alerts.",
        "content": """
Open the voice configuration for the alert you want to change and select
the voice you want EchoStream to use.

After saving your settings, future alerts using that configuration will
use the selected voice.

The voices available to you depend on the selected TTS provider and your
EchoStream plan.
""".strip(),
        "icon": "mic",
        "tags": ["tts", "voice", "audio"],
        "search_keywords": "change TTS voice select voice speech voice settings",
        "sort_order": 1,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "voices",
        "slug": "tts-providers",
        "title": "What TTS providers does EchoStream support?",
        "excerpt": "Learn how EchoStream uses different text-to-speech providers.",
        "content": """
EchoStream supports configurable text-to-speech providers.

The available providers and voices can change as EchoStream adds or
removes integrations.

Your alert configuration determines which provider and voice are used
when generating speech.
""".strip(),
        "icon": "server",
        "tags": ["tts", "providers", "voices"],
        "search_keywords": "TTS providers text speech provider Edge voice provider",
        "sort_order": 2,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # VOICE CLONING
    # =========================================================

    {
        "category": "voice-cloning",
        "slug": "what-is-voice-cloning",
        "title": "What is voice cloning?",
        "excerpt": "Learn how EchoStream's voice cloning feature works.",
        "content": """
Voice cloning allows EchoStream to create a custom voice based on a
recorded voice sample.

Once a supported voice has been created, it can be used with compatible
text-to-speech features.

Voice cloning is available on supported EchoStream plans.
""".strip(),
        "icon": "mic",
        "tags": ["voice", "cloning", "tts"],
        "search_keywords": "voice cloning custom voice clone voice",
        "sort_order": 0,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "voice-cloning",
        "slug": "record-voice-sample",
        "title": "How do I record a voice sample?",
        "excerpt": "Record and upload a sample for voice cloning.",
        "content": """
Open the Voice Cloning section and start a new voice sample.

Follow the recording instructions and speak clearly while recording.
When you finish, stop the recording and upload the sample.

EchoStream uses the uploaded sample to create the custom voice.
""".strip(),
        "icon": "recording",
        "tags": ["voice", "cloning", "recording", "voice-sample"],
        "search_keywords": "record voice sample voice cloning microphone recording upload",
        "sort_order": 1,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "voice-cloning",
        "slug": "voice-cloning-requirements",
        "title": "What makes a good voice sample?",
        "excerpt": "Tips for recording a clear sample for voice cloning.",
        "content": """
Record your sample in a quiet environment with as little background noise
as possible.

Speak naturally and clearly and keep a consistent distance from your
microphone.

Avoid music, loud background sounds and heavy audio processing in the
recording.

A clean sample gives the voice cloning system better source material.
""".strip(),
        "icon": "checkmark-circle",
        "tags": ["voice", "cloning", "recording", "audio"],
        "search_keywords": "good voice sample recording quality microphone noise cloning",
        "sort_order": 2,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # CUSTOM SOUNDS
    # =========================================================

    {
        "category": "sounds",
        "slug": "what-are-custom-alert-sounds",
        "title": "What are custom alert sounds?",
        "excerpt": "Use your own audio files for supported EchoStream alerts.",
        "content": """
Custom alert sounds allow you to use your own audio instead of generated
speech for supported alerts.

You can upload an audio file, preview it and assign it to an alert that
supports custom audio.
""".strip(),
        "icon": "musical-notes",
        "tags": ["sounds", "alerts", "custom-audio"],
        "search_keywords": "custom sounds alert audio custom audio sound effects",
        "sort_order": 0,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "sounds",
        "slug": "upload-custom-alert-sound",
        "title": "How do I upload a custom alert sound?",
        "excerpt": "Upload your own audio and use it with supported alerts.",
        "content": """
Open the custom sounds section and choose the option to add a sound.

Select an audio file from your device. EchoStream uploads the sound so
it can be used by supported alert configurations.

After uploading, you can preview the sound before assigning it to an alert.
""".strip(),
        "icon": "cloud-upload",
        "tags": ["sounds", "upload", "custom-audio"],
        "search_keywords": "upload custom sound audio alert sound file",
        "sort_order": 1,
        "is_featured": True,
        "is_published": True,
    },


    # =========================================================
    # PLANS & BILLING
    # =========================================================

    {
        "category": "plans-billing",
        "slug": "echostream-plans",
        "title": "What EchoStream plans are available?",
        "excerpt": "Learn how EchoStream plans differ and which features they provide.",
        "content": """
EchoStream offers different plans designed for different levels of usage.

Plan features can include different alert capabilities, usage limits,
voice features and voice cloning access.

Your current plan and available upgrade options can be viewed from the
subscription section of the app.
""".strip(),
        "icon": "card",
        "tags": ["plans", "pricing", "subscription"],
        "search_keywords": "EchoStream plans pricing free starter essential pro",
        "sort_order": 0,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "plans-billing",
        "slug": "upgrade-echostream-plan",
        "title": "How do I upgrade my EchoStream plan?",
        "excerpt": "Upgrade your plan to unlock additional EchoStream features.",
        "content": """
Open the subscription or billing section in EchoStream and choose the
plan you want to upgrade to.

Follow the payment flow to complete the upgrade.

Once the payment and subscription state have been confirmed, your account
will receive the features associated with the new plan.
""".strip(),
        "icon": "arrow-up-circle",
        "tags": ["plans", "upgrade", "subscription", "billing"],
        "search_keywords": "upgrade plan subscription payment upgrade EchoStream",
        "sort_order": 1,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "plans-billing",
        "slug": "downgrade-echostream-plan",
        "title": "How do I downgrade my plan?",
        "excerpt": "Manage your subscription when you want to move to a lower plan.",
        "content": """
If your current subscription supports plan changes, you can manage your
plan from the subscription section.

Choose the available downgrade option and follow the billing provider's
instructions.

The timing of a downgrade depends on the type of subscription and its
billing state.
""".strip(),
        "icon": "arrow-down-circle",
        "tags": ["plans", "downgrade", "subscription"],
        "search_keywords": "downgrade plan subscription lower plan billing",
        "sort_order": 2,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "plans-billing",
        "slug": "cancel-subscription",
        "title": "How do I cancel my subscription?",
        "excerpt": "Manage cancellation for your EchoStream subscription.",
        "content": """
Open the subscription management section to see the actions available
for your current plan.

If cancellation is supported for your subscription, EchoStream will
provide the appropriate cancellation option.

The available actions depend on how your plan was purchased and its
current billing status.
""".strip(),
        "icon": "close-circle",
        "tags": ["subscription", "cancel", "billing"],
        "search_keywords": "cancel subscription cancellation billing plan",
        "sort_order": 3,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # ACCOUNT & SETTINGS
    # =========================================================

    {
        "category": "account-settings",
        "slug": "update-profile",
        "title": "How do I update my profile?",
        "excerpt": "Manage the profile information associated with your EchoStream account.",
        "content": """
Open your account settings to view and update the profile information
available to your account.

Save your changes after editing your information.
""".strip(),
        "icon": "person",
        "tags": ["account", "profile", "settings"],
        "search_keywords": "update profile account settings name profile information",
        "sort_order": 0,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "account-settings",
        "slug": "notification-settings",
        "title": "How do notification settings work?",
        "excerpt": "Control which EchoStream notifications you receive.",
        "content": """
EchoStream lets you control supported notification categories from your
notification preferences.

You can enable or disable push notifications and supported notification
categories such as subscription updates, streaming reminders and product
updates.

Your notification preferences do not control TikTok LIVE alert behavior;
those are configured separately.
""".strip(),
        "icon": "notifications",
        "tags": ["notifications", "settings", "push"],
        "search_keywords": "notification settings push notifications subscription streaming reminders product updates",
        "sort_order": 1,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "account-settings",
        "slug": "streaming-reminders",
        "title": "What are streaming reminders?",
        "excerpt": "Learn how EchoStream reminds you when you have not streamed recently.",
        "content": """
EchoStream can send a streaming reminder when you have not streamed for
a period of time.

Streaming reminders can be enabled or disabled from your notification
preferences.

The reminder system uses your streaming activity to determine when a
reminder may be appropriate.
""".strip(),
        "icon": "calendar",
        "tags": ["notifications", "streaming", "reminders"],
        "search_keywords": "streaming reminder notification reminder not streamed",
        "sort_order": 2,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # TROUBLESHOOTING
    # =========================================================

    {
        "category": "troubleshooting",
        "slug": "echostream-is-not-speaking",
        "title": "Why isn't EchoStream speaking?",
        "excerpt": "Check the most common causes of missing TTS audio.",
        "content": """
If EchoStream is not producing speech, first make sure the relevant alert
is enabled.

Check that the Live Runtime is connected and that the event is actually
being received.

Then check your selected TTS provider and voice configuration and make
sure your device volume and audio output are working.

If you are using custom audio, verify that the custom sound is still
available and correctly assigned.
""".strip(),
        "icon": "volume-mute",
        "tags": ["troubleshooting", "tts", "audio", "alerts"],
        "search_keywords": "no sound TTS not speaking audio voice alert silent",
        "sort_order": 0,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "troubleshooting",
        "slug": "tiktok-events-not-triggering",
        "title": "Why aren't my TikTok events triggering alerts?",
        "excerpt": "Troubleshoot alerts that are not responding to LIVE events.",
        "content": """
Make sure the Live Runtime is connected and that your TikTok LIVE session
is active.

Check the specific event preference. For example, if gift alerts are
disabled, receiving a gift will not trigger that alert.

Also check the individual gift configuration if you are troubleshooting
a specific gift.

If the runtime is connected and the relevant alert is enabled but events
still are not being processed, restart the runtime and try again.
""".strip(),
        "icon": "alert-circle",
        "tags": ["troubleshooting", "events", "alerts", "tiktok"],
        "search_keywords": "TikTok events not triggering alerts gifts follows likes runtime",
        "sort_order": 1,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "troubleshooting",
        "slug": "voice-recording-not-working",
        "title": "Why isn't voice recording working?",
        "excerpt": "Troubleshoot microphone and voice sample recording problems.",
        "content": """
Make sure EchoStream has permission to access your microphone.

Check that another application is not preventing microphone access and
that your device has a working microphone.

If permission was previously denied, open your device settings and allow
microphone access for EchoStream.

Then return to the voice recording screen and try recording again.
""".strip(),
        "icon": "mic-off",
        "tags": ["troubleshooting", "voice", "recording", "microphone"],
        "search_keywords": "voice recording not working microphone permission recording error",
        "sort_order": 2,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "troubleshooting",
        "slug": "custom-sound-not-playing",
        "title": "Why isn't my custom sound playing?",
        "excerpt": "Troubleshoot custom audio that does not play during an alert.",
        "content": """
First verify that the custom sound was uploaded successfully and is still
assigned to the alert.

Check that the alert itself is enabled and that the Live Runtime is
connected.

Also check your device volume and audio output.

If the sound still does not play, remove and re-upload the audio file and
try the preview before assigning it again.
""".strip(),
        "icon": "musical-note",
        "tags": ["troubleshooting", "sounds", "audio", "alerts"],
        "search_keywords": "custom sound not playing audio alert sound problem",
        "sort_order": 3,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "troubleshooting",
        "slug": "runtime-wont-connect",
        "title": "What should I do if the runtime won't connect?",
        "excerpt": "Steps to take when EchoStream cannot connect to your TikTok LIVE.",
        "content": """
Check that your TikTok username is correct and that you are currently
able to access TikTok normally.

Verify your internet connection and try starting the runtime again.

If the runtime still cannot connect, stop it completely, wait a moment and
start it again.

If the problem persists, check for other troubleshooting information or
contact EchoStream support.
""".strip(),
        "icon": "wifi",
        "tags": ["troubleshooting", "runtime", "tiktok", "connection"],
        "search_keywords": "runtime won't connect TikTok connection failed unable to connect",
        "sort_order": 4,
        "is_featured": True,
        "is_published": True,
    },
       # =========================================================
    # GETTING STARTED
    # =========================================================

    {
        "category": "getting-started",
        "slug": "how-echostream-works-with-tiktok-live",
        "title": "How does EchoStream work with TikTok LIVE?",
        "excerpt": "Understand how EchoStream receives and responds to events from your LIVE.",
        "content": """
EchoStream connects to your TikTok LIVE session and listens for supported
LIVE events.

When an event is received, EchoStream checks your configured preferences
and determines whether the event should trigger an alert.

Depending on the configuration, EchoStream can then generate speech or
play custom audio in response.
""".strip(),
        "icon": "logo-tiktok",
        "tags": ["getting-started", "tiktok", "live"],
        "search_keywords": "TikTok LIVE EchoStream integration events how it works",
        "sort_order": 3,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "getting-started",
        "slug": "where-to-find-echostream-settings",
        "title": "Where can I find my EchoStream settings?",
        "excerpt": "Find the main settings and configuration areas in EchoStream.",
        "content": """
EchoStream organizes its settings into different feature areas.

Depending on what you want to configure, you can use the Live Runtime,
alert preferences, voice settings, voice cloning, custom sounds,
notifications or subscription sections.

Each area controls a specific part of how EchoStream behaves.
""".strip(),
        "icon": "settings",
        "tags": ["getting-started", "settings", "preferences"],
        "search_keywords": "settings preferences configuration where settings",
        "sort_order": 4,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "getting-started",
        "slug": "what-happens-after-connecting-tiktok",
        "title": "What happens after I connect TikTok?",
        "excerpt": "Understand what EchoStream does after the Live Runtime connects.",
        "content": """
After the Live Runtime establishes a connection, EchoStream begins
monitoring supported events from the LIVE session.

Your configured alert preferences determine which events EchoStream
responds to.

The runtime does not automatically enable every alert. Your preferences
control the behavior of individual event types.
""".strip(),
        "icon": "checkmark-circle",
        "tags": ["getting-started", "tiktok", "runtime"],
        "search_keywords": "after connecting TikTok what happens runtime events",
        "sort_order": 5,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # LIVE RUNTIME
    # =========================================================

    {
        "category": "live-runtime",
        "slug": "how-to-start-live-runtime",
        "title": "How do I start the Live Runtime?",
        "excerpt": "Start EchoStream's LIVE connection from the Live Runtime screen.",
        "content": """
Open the Live Runtime section and make sure your TikTok username is
configured correctly.

Start the runtime and wait for the connection status to indicate that
EchoStream has connected successfully.

Once connected, EchoStream can begin processing supported LIVE events.
""".strip(),
        "icon": "play",
        "tags": ["runtime", "live", "start"],
        "search_keywords": "start runtime start live connection EchoStream",
        "sort_order": 4,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "live-runtime",
        "slug": "how-to-stop-live-runtime",
        "title": "How do I stop the Live Runtime?",
        "excerpt": "Stop the TikTok LIVE connection when you no longer need EchoStream.",
        "content": """
Open the Live Runtime section and use the stop control to disconnect the
runtime.

Once the runtime is stopped, EchoStream will no longer receive new LIVE
events from that connection.
""".strip(),
        "icon": "stop-circle",
        "tags": ["runtime", "live", "stop"],
        "search_keywords": "stop runtime disconnect live EchoStream",
        "sort_order": 5,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "live-runtime",
        "slug": "can-i-use-echostream-before-going-live",
        "title": "Can I configure EchoStream before going LIVE?",
        "excerpt": "Prepare your alerts, voices and settings before starting your stream.",
        "content": """
Yes. You can configure your EchoStream settings before starting your
TikTok LIVE.

It is recommended to configure your alerts, voices and audio settings
before going live so you do not need to make major changes while
streaming.
""".strip(),
        "icon": "options",
        "tags": ["runtime", "setup", "live", "configuration"],
        "search_keywords": "configure before live setup alerts before streaming",
        "sort_order": 6,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "live-runtime",
        "slug": "what-happens-when-a-live-ends",
        "title": "What happens when my TikTok LIVE ends?",
        "excerpt": "Learn how EchoStream handles the end of a LIVE session.",
        "content": """
When your TikTok LIVE session ends, the connection to that LIVE session
is no longer active.

EchoStream cannot process new LIVE events until another active LIVE
connection is available.

Your saved alert and voice preferences remain available for your next
stream.
""".strip(),
        "icon": "exit",
        "tags": ["runtime", "live", "tiktok"],
        "search_keywords": "TikTok live ends runtime after stream stream ended",
        "sort_order": 7,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # ALERTS & TTS
    # =========================================================

    {
        "category": "alerts",
        "slug": "enable-or-disable-alerts",
        "title": "How do I enable or disable an alert?",
        "excerpt": "Turn individual EchoStream event alerts on or off.",
        "content": """
Open your alert preferences and locate the event you want to configure.

Use the toggle associated with that event to enable or disable its alert
behavior.

Disabled alerts will not trigger the corresponding EchoStream response
when that event occurs.
""".strip(),
        "icon": "toggle",
        "tags": ["alerts", "preferences", "events"],
        "search_keywords": "enable disable alert toggle event preferences",
        "sort_order": 5,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "how-gift-alerts-differ-from-event-alerts",
        "title": "How are gift alerts different from other alerts?",
        "excerpt": "Understand the difference between general event alerts and individual gift alerts.",
        "content": """
General event preferences control supported event types such as gifts,
likes and follows.

Gift alerts can additionally be configured for individual gifts.

This allows you to control which specific gifts should receive custom
alert behavior instead of treating every gift identically.
""".strip(),
        "icon": "gift",
        "tags": ["alerts", "gifts", "events", "preferences"],
        "search_keywords": "gift alerts individual gifts event alerts difference",
        "sort_order": 6,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "why-is-my-gift-alert-not-triggering",
        "title": "Why isn't a specific gift alert triggering?",
        "excerpt": "Check the settings that control individual gift alerts.",
        "content": """
First verify that the general gift event is enabled.

Then search for the specific gift in your gift alert settings and make
sure that gift has its alert enabled.

If the alert uses TTS, check the configured voice and provider. If it
uses custom audio, verify that the audio is still available.

The Live Runtime must also be connected to receive the gift event.
""".strip(),
        "icon": "gift",
        "tags": ["alerts", "gifts", "troubleshooting"],
        "search_keywords": "gift alert not triggering specific gift disabled gift",
        "sort_order": 7,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "what-happens-when-many-alerts-arrive",
        "title": "What happens when many alerts arrive at once?",
        "excerpt": "Learn how EchoStream handles multiple events arriving close together.",
        "content": """
EchoStream uses alert processing and queue behavior to prevent multiple
audio responses from interfering with one another.

Events can be processed in sequence rather than attempting to play every
audio response at exactly the same time.

The exact limits and behavior depend on your plan and alert configuration.
""".strip(),
        "icon": "list",
        "tags": ["alerts", "queue", "events"],
        "search_keywords": "many alerts queue multiple events simultaneous alerts",
        "sort_order": 8,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "can-i-use-different-settings-for-different-gifts",
        "title": "Can I use different settings for different gifts?",
        "excerpt": "Configure individual gift alerts independently.",
        "content": """
Yes. EchoStream supports individual gift preferences.

You can search for a specific gift and configure its alert behavior
independently from other gifts.

This allows frequently received or important gifts to have different
responses from other gifts.
""".strip(),
        "icon": "options",
        "tags": ["alerts", "gifts", "preferences"],
        "search_keywords": "different gift settings individual gift preferences",
        "sort_order": 9,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # VOICES & TTS
    # =========================================================

    {
        "category": "voices",
        "slug": "what-is-a-tts-provider",
        "title": "What is a TTS provider?",
        "excerpt": "Understand the service that generates EchoStream's spoken audio.",
        "content": """
A TTS provider is the service EchoStream uses to turn text into spoken
audio.

EchoStream can use supported providers to generate speech for alerts.

The provider and voice selected for an alert determine how that alert
sounds.
""".strip(),
        "icon": "server",
        "tags": ["tts", "providers", "voices"],
        "search_keywords": "TTS provider text speech provider meaning",
        "sort_order": 3,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "voices",
        "slug": "why-is-my-tts-voice-unavailable",
        "title": "Why is a TTS voice unavailable?",
        "excerpt": "Understand why a voice may not be available for your configuration.",
        "content": """
Voice availability can depend on the selected TTS provider and your
EchoStream plan.

A voice may also become unavailable if a provider changes its available
voices or if the provider is temporarily unavailable.

Try selecting another supported voice or provider if one is available.
""".strip(),
        "icon": "help-circle",
        "tags": ["tts", "voices", "providers", "troubleshooting"],
        "search_keywords": "voice unavailable TTS voice missing provider",
        "sort_order": 4,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "voices",
        "slug": "can-i-use-a-cloned-voice-for-tts",
        "title": "Can I use a cloned voice for TTS?",
        "excerpt": "Learn how cloned voices can be used with supported speech features.",
        "content": """
Supported EchoStream plans can use cloned voices with compatible
text-to-speech features.

After a voice has been successfully created, it can be selected anywhere
that supports that type of voice.

The exact availability depends on the voice provider and your plan.
""".strip(),
        "icon": "person",
        "tags": ["tts", "voice-cloning", "voices"],
        "search_keywords": "cloned voice TTS use clone voice speech",
        "sort_order": 5,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "voices",
        "slug": "why-does-my-tts-sound-different",
        "title": "Why does my TTS voice sound different?",
        "excerpt": "Learn what can affect the sound of generated speech.",
        "content": """
Generated speech can vary depending on the selected provider, voice and
the text being spoken.

Punctuation, capitalization and the structure of the alert text can also
affect how speech is produced.

If you changed your provider or voice recently, make sure the new
configuration has been saved.
""".strip(),
        "icon": "volume-high",
        "tags": ["tts", "voice", "audio"],
        "search_keywords": "TTS sounds different voice changed speech audio quality",
        "sort_order": 6,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # VOICE CLONING
    # =========================================================

    {
        "category": "voice-cloning",
        "slug": "how-long-does-voice-cloning-take",
        "title": "How long does voice cloning take?",
        "excerpt": "Learn what happens after you submit a voice sample.",
        "content": """
After you upload a voice sample, EchoStream processes the sample through
the voice cloning system.

Processing time can vary depending on the voice provider and current
service conditions.

Your voice becomes available once processing has completed successfully.
""".strip(),
        "icon": "time",
        "tags": ["voice-cloning", "processing", "voice"],
        "search_keywords": "voice cloning processing time how long sample",
        "sort_order": 3,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "voice-cloning",
        "slug": "can-i-preview-my-cloned-voice",
        "title": "Can I preview my cloned voice?",
        "excerpt": "Preview a cloned voice before using it for your alerts.",
        "content": """
Where preview is available, you can generate a sample of speech using
your cloned voice before assigning it to your alert configuration.

A preview lets you verify that the resulting voice sounds the way you
expect before using it during a LIVE.
""".strip(),
        "icon": "play-circle",
        "tags": ["voice-cloning", "preview", "voice"],
        "search_keywords": "preview cloned voice voice sample test clone",
        "sort_order": 4,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "voice-cloning",
        "slug": "why-did-my-voice-sample-fail",
        "title": "Why did my voice sample fail?",
        "excerpt": "Common reasons a voice sample may not process successfully.",
        "content": """
A voice sample can fail if the recording is unclear, contains excessive
background noise or does not meet the requirements of the voice provider.

Make sure microphone access is allowed and record in a quiet environment.

If a sample fails repeatedly, record a new sample with clearer audio and
try again.
""".strip(),
        "icon": "alert-circle",
        "tags": ["voice-cloning", "troubleshooting", "recording"],
        "search_keywords": "voice sample failed cloning error recording failed",
        "sort_order": 5,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "voice-cloning",
        "slug": "how-to-manage-cloned-voices",
        "title": "How do I manage my cloned voices?",
        "excerpt": "Manage the custom voices associated with your EchoStream account.",
        "content": """
Your cloned voices can be managed from the Voice Cloning section.

Depending on the available actions, you can preview a voice, select it
for supported TTS configurations or remove it when it is no longer needed.

Deleting a voice may prevent existing configurations from using it.
""".strip(),
        "icon": "people",
        "tags": ["voice-cloning", "voices", "management"],
        "search_keywords": "manage cloned voices delete preview select custom voice",
        "sort_order": 6,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # CUSTOM SOUNDS
    # =========================================================

    {
        "category": "sounds",
        "slug": "preview-custom-sound",
        "title": "How do I preview a custom sound?",
        "excerpt": "Listen to uploaded audio before using it in an alert.",
        "content": """
Open your custom sounds and select the sound you want to preview.

EchoStream can download and play the sound locally so you can verify the
audio before assigning it to an alert.
""".strip(),
        "icon": "play",
        "tags": ["sounds", "preview", "audio"],
        "search_keywords": "preview custom sound listen audio",
        "sort_order": 2,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "sounds",
        "slug": "replace-custom-alert-sound",
        "title": "How do I replace a custom alert sound?",
        "excerpt": "Replace an existing custom audio file with a new one.",
        "content": """
Open the custom sound associated with your alert and choose the replace
or upload option.

The new audio is uploaded and becomes the sound associated with the
configuration.

Preview the replacement before using it during a LIVE.
""".strip(),
        "icon": "refresh",
        "tags": ["sounds", "replace", "audio", "alerts"],
        "search_keywords": "replace custom sound change audio alert sound",
        "sort_order": 3,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "sounds",
        "slug": "delete-custom-alert-sound",
        "title": "How do I delete a custom sound?",
        "excerpt": "Remove custom audio you no longer want to use.",
        "content": """
Open your custom sounds and select the sound you want to remove.

Deleting a sound removes it from your available custom audio. If an alert
was using that sound, you should update the alert configuration before
expecting custom audio to play again.
""".strip(),
        "icon": "trash",
        "tags": ["sounds", "delete", "audio"],
        "search_keywords": "delete custom sound remove audio alert",
        "sort_order": 4,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # PLANS & BILLING
    # =========================================================

    {
        "category": "plans-billing",
        "slug": "how-do-i-see-my-current-plan",
        "title": "How do I see my current plan?",
        "excerpt": "Find your current EchoStream subscription and plan information.",
        "content": """
Open the subscription or billing section of EchoStream.

Your current plan and its subscription status are displayed there,
along with any management actions available to your account.
""".strip(),
        "icon": "card",
        "tags": ["plans", "billing", "subscription"],
        "search_keywords": "current plan subscription status billing plan",
        "sort_order": 4,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "plans-billing",
        "slug": "why-cant-i-access-a-feature",
        "title": "Why can't I access a feature?",
        "excerpt": "Understand how your EchoStream plan affects feature access.",
        "content": """
Some EchoStream features are restricted to specific plans.

If a feature is unavailable, check your current subscription and the
requirements for that feature.

For example, voice cloning and certain alert capabilities may depend on
your plan.
""".strip(),
        "icon": "lock-closed",
        "tags": ["plans", "features", "subscription"],
        "search_keywords": "feature locked unavailable plan subscription access",
        "sort_order": 5,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "plans-billing",
        "slug": "subscription-management",
        "title": "Where can I manage my subscription?",
        "excerpt": "Find the subscription management options available to your account.",
        "content": """
Open the billing or subscription section in EchoStream.

Depending on your current plan and billing status, you may see options
such as upgrading, downgrading or cancelling.

The available actions can differ between recurring subscriptions and
other types of purchases.
""".strip(),
        "icon": "settings",
        "tags": ["subscription", "billing", "management"],
        "search_keywords": "manage subscription billing upgrade downgrade cancel",
        "sort_order": 6,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "plans-billing",
        "slug": "why-is-an-upgrade-not-available",
        "title": "Why can't I upgrade my plan?",
        "excerpt": "Understand why a plan change may not be available.",
        "content": """
Plan changes depend on your current subscription state and the billing
options available to your account.

If an upgrade is unavailable, check whether you already have an active
subscription or another pending billing state.

If the problem continues, contact support with the details of your
current plan and the upgrade you are trying to make.
""".strip(),
        "icon": "alert-circle",
        "tags": ["billing", "upgrade", "subscription", "troubleshooting"],
        "search_keywords": "upgrade unavailable cannot upgrade subscription billing error",
        "sort_order": 7,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # ACCOUNT & SETTINGS
    # =========================================================

    {
        "category": "account-settings",
        "slug": "what-are-push-notifications",
        "title": "What are EchoStream push notifications?",
        "excerpt": "Understand notifications EchoStream can send outside your LIVE.",
        "content": """
Push notifications allow EchoStream to notify you about supported account
and product events even when you are not actively using the app.

Examples include subscription updates, streaming reminders and product
updates.

Push notifications are separate from TikTok LIVE alerts.
""".strip(),
        "icon": "notifications",
        "tags": ["notifications", "push", "account"],
        "search_keywords": "push notifications EchoStream notification types",
        "sort_order": 3,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "account-settings",
        "slug": "disable-push-notifications",
        "title": "How do I disable push notifications?",
        "excerpt": "Turn off EchoStream push notifications from your notification preferences.",
        "content": """
Open your notification preferences and disable push notifications.

When push notifications are disabled, EchoStream will not deliver
supported push notifications to your device.

This does not disable LIVE alert processing or TTS.
""".strip(),
        "icon": "notifications-off",
        "tags": ["notifications", "push", "settings"],
        "search_keywords": "disable push notifications turn off notifications",
        "sort_order": 4,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "account-settings",
        "slug": "product-update-notifications",
        "title": "What are product update notifications?",
        "excerpt": "Learn about notifications for new EchoStream features and updates.",
        "content": """
Product update notifications are used to tell you about relevant EchoStream
product changes, new features and other updates.

You can control whether you receive these notifications from your
notification preferences.
""".strip(),
        "icon": "megaphone",
        "tags": ["notifications", "product-updates", "settings"],
        "search_keywords": "product updates notifications new features announcements",
        "sort_order": 5,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "account-settings",
        "slug": "subscription-notifications",
        "title": "What are subscription notifications?",
        "excerpt": "Learn about notifications related to your EchoStream subscription.",
        "content": """
Subscription notifications keep you informed about supported changes to
your EchoStream billing or subscription state.

You can control these notifications from your notification preferences.
""".strip(),
        "icon": "card",
        "tags": ["notifications", "subscription", "billing"],
        "search_keywords": "subscription notifications billing notification plan changes",
        "sort_order": 6,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # TROUBLESHOOTING
    # =========================================================

    {
        "category": "troubleshooting",
        "slug": "echostream-alert-is-delayed",
        "title": "Why is my alert delayed?",
        "excerpt": "Understand why an alert may take time to play after an event.",
        "content": """
An alert may be delayed when multiple events arrive close together and
are waiting in the alert queue.

TTS generation can also take some time depending on the selected provider
and current network conditions.

If alerts are consistently delayed even when there is no queue, check
your network connection and TTS provider configuration.
""".strip(),
        "icon": "time",
        "tags": ["troubleshooting", "alerts", "queue", "tts"],
        "search_keywords": "alert delayed slow TTS queue audio delay",
        "sort_order": 5,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "troubleshooting",
        "slug": "echostream-says-wrong-text",
        "title": "Why is EchoStream saying the wrong text?",
        "excerpt": "Check your alert template and event configuration.",
        "content": """
Check the template configured for the alert.

Dynamic tokens can insert information from the event, such as the
username or event description.

If the spoken text is unexpected, review the template and make sure the
correct event configuration is being used.
""".strip(),
        "icon": "chatbox",
        "tags": ["troubleshooting", "tts", "templates", "alerts"],
        "search_keywords": "wrong text TTS says wrong thing alert template username event",
        "sort_order": 6,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "troubleshooting",
        "slug": "echostream-cannot-access-microphone",
        "title": "Why can't EchoStream access my microphone?",
        "excerpt": "Fix microphone permission problems when recording voice samples.",
        "content": """
Voice recording requires microphone permission.

If EchoStream cannot access your microphone, open your device's app
permissions and make sure microphone access is allowed.

After granting permission, return to EchoStream and try recording again.

If permission is already enabled but recording still fails, restart the
app and try again.
""".strip(),
        "icon": "mic-off",
        "tags": ["troubleshooting", "microphone", "permissions", "voice"],
        "search_keywords": "microphone permission cannot access microphone voice recording",
        "sort_order": 7,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "troubleshooting",
        "slug": "echostream-app-not-loading",
        "title": "What should I do if EchoStream is not loading?",
        "excerpt": "Basic steps for resolving app loading problems.",
        "content": """
First check your internet connection and make sure other apps can access
the internet normally.

Close and reopen EchoStream and try again.

If the problem continues, make sure you are using the latest available
version of the app.

Persistent loading problems may be caused by a temporary service issue.
If the problem continues, contact support.
""".strip(),
        "icon": "refresh",
        "tags": ["troubleshooting", "app", "loading", "connection"],
        "search_keywords": "EchoStream not loading app stuck loading connection",
        "sort_order": 8,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "troubleshooting",
        "slug": "what-to-do-before-contacting-support",
        "title": "What information should I provide when contacting support?",
        "excerpt": "Give support the information they need to investigate your problem.",
        "content": """
When contacting support, describe what you were trying to do and what
happened instead.

Include the relevant feature, such as Live Runtime, TTS, voice cloning,
alerts or billing.

If possible, include the exact error message, the approximate time the
problem occurred and the steps that caused it.

Avoid sharing passwords, payment credentials or other sensitive
information.
""".strip(),
        "icon": "help-circle",
        "tags": ["troubleshooting", "support", "help"],
        "search_keywords": "contact support report problem error information help",
        "sort_order": 9,
        "is_featured": True,
        "is_published": True,
    },
        # =========================================================
    # GETTING STARTED
    # =========================================================

    {
        "category": "getting-started",
        "slug": "first-time-echostream-setup",
        "title": "What should I configure before my first stream?",
        "excerpt": "A quick checklist for preparing EchoStream before your first LIVE.",
        "content": """
Before your first stream, make sure your account is configured and your
TikTok username is correct.

Then configure the alerts you want EchoStream to handle, choose your
preferred TTS voice, and check your audio output.

If you plan to use voice cloning or custom sounds, configure those before
going LIVE so you can test everything in advance.

Finally, start the Live Runtime and confirm that it connects successfully.
""".strip(),
        "icon": "checkmark-done",
        "tags": ["getting-started", "setup", "live", "configuration"],
        "search_keywords": "first setup checklist configure before stream first LIVE",
        "sort_order": 6,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "getting-started",
        "slug": "test-echostream-before-live",
        "title": "How can I test EchoStream before going LIVE?",
        "excerpt": "Prepare and verify your EchoStream configuration before streaming.",
        "content": """
You can prepare your alert, voice and audio configuration before starting
your TikTok LIVE.

Check that your selected voice is correct, preview custom sounds where
available, and verify that your device audio is working.

Starting the Live Runtime when your TikTok session is available allows
EchoStream to receive LIVE events.
""".strip(),
        "icon": "flask",
        "tags": ["getting-started", "testing", "setup"],
        "search_keywords": "test EchoStream before live test alerts audio voice",
        "sort_order": 7,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "getting-started",
        "slug": "does-echostream-save-my-preferences",
        "title": "Does EchoStream save my preferences?",
        "excerpt": "Understand how your EchoStream configuration is retained.",
        "content": """
Your EchoStream configuration is associated with your account so your
settings can be used again when you return to the app.

This includes supported alert, voice, notification and other account
preferences.

Some runtime state, such as an active TikTok LIVE connection, is separate
from your saved configuration.
""".strip(),
        "icon": "save",
        "tags": ["getting-started", "preferences", "settings"],
        "search_keywords": "save preferences settings configuration account",
        "sort_order": 8,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # LIVE RUNTIME
    # =========================================================

    {
        "category": "live-runtime",
        "slug": "how-do-i-know-runtime-is-connected",
        "title": "How do I know when the Live Runtime is connected?",
        "excerpt": "Check the runtime status before relying on LIVE alerts.",
        "content": """
The Live Runtime displays its current connection state in the runtime
section.

Before expecting alerts to work, make sure the runtime indicates that it
has successfully connected to your TikTok LIVE session.

If the runtime is disconnected, EchoStream cannot receive new LIVE events.
""".strip(),
        "icon": "wifi",
        "tags": ["runtime", "connection", "status"],
        "search_keywords": "runtime connected status connection state TikTok LIVE",
        "sort_order": 8,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "live-runtime",
        "slug": "can-i-change-settings-while-live",
        "title": "Can I change EchoStream settings while LIVE?",
        "excerpt": "Learn which EchoStream settings can be adjusted during a stream.",
        "content": """
Many EchoStream preferences can be changed while you are using the app.

For settings that affect future alerts, changes are applied to subsequent
events after the configuration has been updated.

Avoid making major runtime changes if your connection is currently being
used for an active stream unless necessary.
""".strip(),
        "icon": "options",
        "tags": ["runtime", "settings", "live", "preferences"],
        "search_keywords": "change settings while live edit preferences streaming",
        "sort_order": 9,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "live-runtime",
        "slug": "does-reconnecting-lose-my-settings",
        "title": "Does reconnecting the runtime reset my settings?",
        "excerpt": "Understand the difference between runtime state and saved preferences.",
        "content": """
Restarting or reconnecting the Live Runtime does not normally mean that
your saved alert and voice preferences are erased.

Your account configuration is separate from the temporary runtime
connection.

After reconnecting, EchoStream uses your saved configuration when
processing supported events.
""".strip(),
        "icon": "refresh-circle",
        "tags": ["runtime", "reconnect", "settings"],
        "search_keywords": "reconnect runtime reset settings preferences",
        "sort_order": 10,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "live-runtime",
        "slug": "why-runtime-stops-working-during-live",
        "title": "Why did the runtime stop working during my LIVE?",
        "excerpt": "Common causes of a runtime interruption during a stream.",
        "content": """
A runtime connection can be interrupted by network problems, the TikTok
LIVE session ending or an unexpected connection error.

Check the runtime status and your internet connection.

If the connection has been lost, reconnect the runtime and verify that it
returns to a connected state.
""".strip(),
        "icon": "warning",
        "tags": ["runtime", "connection", "troubleshooting"],
        "search_keywords": "runtime stopped during live disconnected stream connection lost",
        "sort_order": 11,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "live-runtime",
        "slug": "why-does-runtime-take-time-to-connect",
        "title": "Why does the Live Runtime take time to connect?",
        "excerpt": "Understand why a LIVE connection may not become ready immediately.",
        "content": """
The runtime needs to establish a connection to the TikTok LIVE session
before it can process events.

Connection time can depend on your network and the state of the LIVE
session.

Wait for the runtime to report a successful connection before testing
LIVE events.
""".strip(),
        "icon": "time",
        "tags": ["runtime", "connection", "tiktok"],
        "search_keywords": "runtime slow connecting takes time connection delay",
        "sort_order": 12,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # ALERTS & TTS
    # =========================================================

    {
        "category": "alerts",
        "slug": "what-events-can-trigger-alerts",
        "title": "What TikTok events can trigger EchoStream alerts?",
        "excerpt": "Learn about the LIVE events supported by EchoStream's alert system.",
        "content": """
EchoStream supports configurable responses for supported TikTok LIVE
events.

The alert system currently includes event types such as gifts, follows
and likes.

Available event types and their behavior can evolve as EchoStream adds
new integrations.
""".strip(),
        "icon": "flash",
        "tags": ["alerts", "events", "tiktok"],
        "search_keywords": "supported TikTok events gifts follows likes alerts",
        "sort_order": 10,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "how-do-i-disable-gift-alerts",
        "title": "How do I disable gift alerts?",
        "excerpt": "Stop EchoStream from responding to gift events.",
        "content": """
Open your alert preferences and disable the gift event.

You can also manage individual gift configurations when you want to
disable a particular gift rather than all gift alerts.

Disabling an alert prevents the corresponding EchoStream response when
the event is received.
""".strip(),
        "icon": "gift",
        "tags": ["alerts", "gifts", "disable"],
        "search_keywords": "disable gift alerts turn off gifts gift notifications",
        "sort_order": 11,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "how-do-i-disable-follow-alerts",
        "title": "How do I disable follow alerts?",
        "excerpt": "Turn off EchoStream responses to new followers.",
        "content": """
Open your alert preferences and disable the follow event.

Once disabled, new follow events will no longer trigger the configured
EchoStream alert response.
""".strip(),
        "icon": "person-add",
        "tags": ["alerts", "follows", "disable"],
        "search_keywords": "disable follow alerts turn off follower alerts",
        "sort_order": 12,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "how-do-i-disable-like-alerts",
        "title": "How do I disable like alerts?",
        "excerpt": "Turn off EchoStream responses to TikTok likes.",
        "content": """
Open your alert preferences and disable the like event.

Once disabled, incoming like events will no longer trigger the configured
EchoStream alert response.
""".strip(),
        "icon": "heart-dislike",
        "tags": ["alerts", "likes", "disable"],
        "search_keywords": "disable like alerts turn off likes TikTok",
        "sort_order": 13,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "what-do-alert-tokens-mean",
        "title": "What do alert template tokens mean?",
        "excerpt": "Understand dynamic values used in EchoStream alert templates.",
        "content": """
Alert template tokens are placeholders that EchoStream replaces with
information from the event.

For example, a user token can be replaced with the name of the viewer who
triggered an event.

The available tokens depend on the type of alert being configured.
""".strip(),
        "icon": "code",
        "tags": ["alerts", "templates", "tokens", "tts"],
        "search_keywords": "alert tokens template variables user event placeholders",
        "sort_order": 14,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "alerts",
        "slug": "can-alerts-use-custom-audio-instead-of-tts",
        "title": "Can an alert use custom audio instead of TTS?",
        "excerpt": "Use uploaded audio for supported alerts instead of generated speech.",
        "content": """
Supported alert configurations can use custom audio instead of generated
TTS.

Upload a custom sound, then assign it to an alert that supports custom
audio.

When that alert is triggered, EchoStream can use the configured custom
audio instead of generating speech.
""".strip(),
        "icon": "musical-note",
        "tags": ["alerts", "custom-audio", "tts", "sounds"],
        "search_keywords": "custom audio instead TTS alert sound",
        "sort_order": 15,
        "is_featured": True,
        "is_published": True,
    },


    # =========================================================
    # VOICES & TTS
    # =========================================================

    {
        "category": "voices",
        "slug": "can-each-alert-have-a-different-voice",
        "title": "Can different alerts use different voices?",
        "excerpt": "Configure voices independently for supported alert types.",
        "content": """
EchoStream stores TTS configuration as part of an alert's preferences.

Where supported, you can configure different alerts with different voice
settings.

This allows one type of event to use one voice while another event uses
a different voice.
""".strip(),
        "icon": "people",
        "tags": ["voices", "tts", "alerts"],
        "search_keywords": "different voice per alert multiple TTS voices",
        "sort_order": 7,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "voices",
        "slug": "what-happens-if-no-voice-is-selected",
        "title": "What happens if no voice is selected?",
        "excerpt": "Understand how EchoStream handles an unset voice configuration.",
        "content": """
If an alert does not have a specific voice selected, EchoStream can use
the provider's configured default behavior where supported.

Voice availability depends on the selected provider and your account
configuration.

If an alert does not produce speech, check its provider and voice settings.
""".strip(),
        "icon": "help-circle",
        "tags": ["voices", "tts", "settings"],
        "search_keywords": "no voice selected default voice TTS voice empty",
        "sort_order": 8,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "voices",
        "slug": "how-to-choose-a-voice-for-an-alert",
        "title": "How do I choose a voice for an alert?",
        "excerpt": "Select the TTS provider and voice used by an alert.",
        "content": """
Open the alert's voice configuration and select a supported TTS provider
and voice.

Save the configuration after making your selection.

Future alerts using that configuration will use the selected voice.
""".strip(),
        "icon": "options",
        "tags": ["voices", "tts", "alerts", "settings"],
        "search_keywords": "select choose voice alert TTS provider voice settings",
        "sort_order": 9,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "voices",
        "slug": "voice-cloning-vs-standard-tts",
        "title": "What is the difference between cloned voices and standard TTS voices?",
        "excerpt": "Understand the difference between provider voices and your custom cloned voice.",
        "content": """
Standard TTS voices are voices provided by a supported text-to-speech
provider.

A cloned voice is created from a voice sample and is associated with your
account.

Standard voices can be selected directly from the available provider
voices, while cloned voices require the voice cloning process first.
""".strip(),
        "icon": "git-compare",
        "tags": ["voices", "tts", "voice-cloning"],
        "search_keywords": "cloned voice standard voice TTS difference provider",
        "sort_order": 10,
        "is_featured": True,
        "is_published": True,
    },


    # =========================================================
    # VOICE CLONING
    # =========================================================

    {
        "category": "voice-cloning",
        "slug": "can-i-record-a-new-voice-sample",
        "title": "Can I record a new voice sample?",
        "excerpt": "Create another voice sample when you want to try a different recording.",
        "content": """
Yes. You can record a new voice sample from the Voice Cloning section.

A new sample can be useful when you want to improve the source recording
or create another custom voice.

Make sure the new recording is clear and has minimal background noise.
""".strip(),
        "icon": "add-circle",
        "tags": ["voice-cloning", "recording", "voice-sample"],
        "search_keywords": "new voice sample rerecord voice recording clone",
        "sort_order": 7,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "voice-cloning",
        "slug": "can-i-delete-a-voice-sample",
        "title": "Can I delete a voice sample?",
        "excerpt": "Manage voice samples you no longer need.",
        "content": """
Voice samples can be managed from the voice cloning area when the
corresponding management option is available.

Before deleting a sample or cloned voice, make sure you understand whether
any existing TTS configuration depends on it.
""".strip(),
        "icon": "trash",
        "tags": ["voice-cloning", "voice-sample", "delete"],
        "search_keywords": "delete voice sample remove voice recording cloning",
        "sort_order": 8,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "voice-cloning",
        "slug": "why-voice-cloning-is-not-available",
        "title": "Why isn't voice cloning available?",
        "excerpt": "Check why voice cloning may not be available on your account.",
        "content": """
Voice cloning is a plan-dependent feature.

If the voice cloning section or its actions are unavailable, check your
current EchoStream plan.

Your account also needs microphone access when recording a new sample.
""".strip(),
        "icon": "lock-closed",
        "tags": ["voice-cloning", "plans", "permissions"],
        "search_keywords": "voice cloning unavailable locked plan access",
        "sort_order": 9,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "voice-cloning",
        "slug": "how-to-get-a-clearer-cloned-voice",
        "title": "How can I get a better cloned voice?",
        "excerpt": "Improve the source recording used for voice cloning.",
        "content": """
Use a quiet room and a microphone that produces clear audio.

Speak naturally and consistently instead of moving around or changing
your distance from the microphone.

Avoid background music, fans, loud environmental noise and unnecessary
audio effects.

If the resulting voice does not sound right, recording a cleaner sample
may improve the result.
""".strip(),
        "icon": "sparkles",
        "tags": ["voice-cloning", "recording", "audio", "quality"],
        "search_keywords": "better cloned voice improve voice clone recording quality",
        "sort_order": 10,
        "is_featured": True,
        "is_published": True,
    },


    # =========================================================
    # CUSTOM SOUNDS
    # =========================================================

    {
        "category": "sounds",
        "slug": "where-are-my-custom-sounds-stored",
        "title": "Where are my custom sounds stored?",
        "excerpt": "Understand how uploaded custom alert audio is associated with your account.",
        "content": """
Custom sounds uploaded through EchoStream are associated with your
account and can be managed from the custom sounds section.

The app can download the sound when it needs to preview or play it.
""".strip(),
        "icon": "folder",
        "tags": ["sounds", "storage", "custom-audio"],
        "search_keywords": "custom sounds stored audio files account",
        "sort_order": 5,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "sounds",
        "slug": "can-i-use-a-custom-sound-for-gifts",
        "title": "Can I use a custom sound for a gift alert?",
        "excerpt": "Use custom audio for supported gift alert configurations.",
        "content": """
Supported gift alerts can use custom audio when the feature is available
to your account.

Select the gift you want to configure and assign the appropriate custom
sound.

Make sure the sound has been uploaded successfully before using it.
""".strip(),
        "icon": "gift",
        "tags": ["sounds", "gifts", "custom-audio", "alerts"],
        "search_keywords": "custom sound gift alert gift audio",
        "sort_order": 6,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "sounds",
        "slug": "what-happens-if-i-delete-a-sound-used-by-an-alert",
        "title": "What happens if I delete a sound used by an alert?",
        "excerpt": "Understand the effect of deleting audio assigned to an alert.",
        "content": """
If you remove a custom sound that an alert depends on, that alert may no
longer be able to play the custom audio.

After deleting a sound, review any alerts that were using it and assign
another sound or switch the alert to a supported TTS configuration.
""".strip(),
        "icon": "warning",
        "tags": ["sounds", "alerts", "delete", "custom-audio"],
        "search_keywords": "delete sound assigned alert missing custom audio",
        "sort_order": 7,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # PLANS & BILLING
    # =========================================================

    {
        "category": "plans-billing",
        "slug": "why-does-my-plan-limit-alerts",
        "title": "Why does my plan limit some alerts?",
        "excerpt": "Understand why certain alert capabilities can depend on your plan.",
        "content": """
EchoStream plans can include different limits and feature access.

Some alert capabilities, such as certain custom or advanced alert
configurations, may be restricted depending on your plan.

If you reach a plan limit, the app will indicate when an upgrade is
required for the relevant feature.
""".strip(),
        "icon": "lock-closed",
        "tags": ["plans", "alerts", "limits"],
        "search_keywords": "plan alert limit restricted alerts feature limit upgrade",
        "sort_order": 8,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "plans-billing",
        "slug": "what-happens-after-canceling",
        "title": "What happens after I cancel my subscription?",
        "excerpt": "Understand what cancellation means for your subscription.",
        "content": """
When a supported subscription is cancelled, the billing provider handles
the cancellation according to the subscription's billing state.

Your access to paid features may remain available for the applicable
period depending on the subscription terms.

Check your subscription management screen for the current status of your
plan.
""".strip(),
        "icon": "calendar",
        "tags": ["billing", "subscription", "cancel"],
        "search_keywords": "cancel subscription what happens after cancellation paid features",
        "sort_order": 9,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "plans-billing",
        "slug": "why-does-my-plan-show-the-wrong-status",
        "title": "Why does my subscription show the wrong status?",
        "excerpt": "What to check when your displayed subscription status looks incorrect.",
        "content": """
Subscription status can depend on the latest information received from
the billing system.

If you recently upgraded, downgraded or cancelled, the displayed state
may take some time to reflect the latest billing information.

If the status remains incorrect, contact support and provide the details
of the plan change you made.
""".strip(),
        "icon": "sync",
        "tags": ["billing", "subscription", "status", "troubleshooting"],
        "search_keywords": "wrong subscription status billing plan status not updated",
        "sort_order": 10,
        "is_featured": False,
        "is_published": True,
    },


    # =========================================================
    # ACCOUNT & SETTINGS
    # =========================================================

    {
        "category": "account-settings",
        "slug": "streaming-reminder-not-working",
        "title": "Why didn't I receive a streaming reminder?",
        "excerpt": "Check the settings that control streaming reminder notifications.",
        "content": """
Make sure push notifications are enabled and that streaming reminders
are enabled in your notification preferences.

Streaming reminders are based on your recent streaming activity, so a
reminder is not generated every time you open the app.

If notifications are enabled but you still do not receive reminders,
check your device's notification permissions as well.
""".strip(),
        "icon": "notifications",
        "tags": ["notifications", "streaming-reminders", "troubleshooting"],
        "search_keywords": "streaming reminder not received reminder notification missing",
        "sort_order": 7,
        "is_featured": True,
        "is_published": True,
    },

    {
        "category": "account-settings",
        "slug": "push-notification-permission",
        "title": "Why aren't EchoStream push notifications appearing?",
        "excerpt": "Check app and device notification permissions.",
        "content": """
First make sure push notifications are enabled in EchoStream's
notification preferences.

Then check your device's system notification settings and make sure
EchoStream is allowed to send notifications.

If both are enabled and notifications are still missing, make sure the
device has an active internet connection.
""".strip(),
        "icon": "notifications-circle",
        "tags": ["notifications", "push", "troubleshooting"],
        "search_keywords": "push notification not appearing missing notification permission",
        "sort_order": 8,
        "is_featured": False,
        "is_published": True,
    },

    {
        "category": "account-settings",
        "slug": "notification-settings-vs-live-alert-settings",
        "title": "What is the difference between notifications and LIVE alerts?",
        "excerpt": "Understand the two different notification systems in EchoStream.",
        "content": """
EchoStream has two different concepts.

LIVE alerts are responses to events happening during your TikTok LIVE.
They can include TTS and custom audio.

Push notifications are messages EchoStream sends to your device about
supported account, subscription, streaming or product events.

Changing push notification settings does not disable your LIVE alerts.
""".strip(),
        "icon": "git-compare",
        "tags": ["notifications", "alerts", "settings"],
        "search_keywords": "difference push notifications LIVE alerts TTS",
        "sort_order": 9,
        "is_featured": True,
        "is_published": True,
    },
]

