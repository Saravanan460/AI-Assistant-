"""
═══════════════════════════════════════════════════════════════════════════
  TELEX AI ASSISTANT — FUTURISTIC UI
  A premium, Jarvis-inspired interface with particle visualizer,
  glassmorphism panels, and micro-animations.
  
  Public API (unchanged from original):
    ChatApplication(root, voice_handler, chat_logic)
    .set_llm_handler(llm_handler)
    .toggle_voice_mode()
    .send_message(event=None, text=None)
    .display_message(sender, message)
═══════════════════════════════════════════════════════════════════════════
"""

import customtkinter as ctk
import threading
import tkinter as tk
import math
import random
import time
import config

# ─────────────────────────────────────────────────────────────────────────
# DESIGN SYSTEM
# ─────────────────────────────────────────────────────────────────────────

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")


class DesignTokens:
    """Centralized design system constants — the single source of truth."""

    # ── Backgrounds ──
    BG_PRIMARY    = "#050510"    # Deep space black
    BG_SURFACE    = "#0A0A1A"    # Panel surface
    BG_GLASS      = "#0D0D20"    # Glassmorphism panel fill
    BG_GLASS_ALT  = "#10102A"    # Slightly lighter glass
    BG_INPUT      = "#0E0E24"    # Input field background

    # ── Accent Colors ──
    ACCENT_CYAN   = "#00F0FF"    # Primary — idle, links
    ACCENT_PURPLE = "#A855F7"    # Secondary — thinking
    ACCENT_PINK   = "#FF00AA"    # Tertiary — speaking
    ACCENT_GREEN  = "#00FF88"    # Success — listening
    ACCENT_BLUE   = "#3B82F6"    # User bubbles
    ACCENT_RED    = "#EF4444"    # Errors, close buttons

    # ── Text ──
    TEXT_PRIMARY  = "#E8E8F0"
    TEXT_SECONDARY = "#A0A0B8"
    TEXT_DIM      = "#5A5A70"
    TEXT_ACCENT   = "#00F0FF"

    # ── Borders ──
    BORDER_GLASS  = "#1A1A3A"
    BORDER_GLOW   = "#00F0FF"

    # ── Fonts ──
    FONT_HEADING  = ("Segoe UI", 28, "bold")
    FONT_TITLE    = ("Segoe UI", 16, "bold")
    FONT_BODY     = ("Segoe UI", 13)
    FONT_BODY_SM  = ("Segoe UI", 11)
    FONT_MONO     = ("Consolas", 12)
    FONT_MONO_SM  = ("Consolas", 10)
    FONT_STATUS   = ("Segoe UI", 20)
    FONT_LABEL    = ("Segoe UI", 10, "bold")

    # ── Layout ──
    CORNER_RADIUS = 16
    CORNER_SM     = 10
    CORNER_LG     = 20
    PAD           = 12
    PAD_SM        = 6
    PAD_LG        = 20

    # ── State Color Map ──
    STATE_COLORS = {
        "idle":      {"primary": "#00F0FF", "secondary": "#0066AA", "glow": "#00F0FF40"},
        "listening": {"primary": "#00FF88", "secondary": "#00AA55", "glow": "#00FF8840"},
        "thinking":  {"primary": "#A855F7", "secondary": "#6B21A8", "glow": "#A855F740"},
        "speaking":  {"primary": "#FF00AA", "secondary": "#AA0077", "glow": "#FF00AA40"},
        "sleeping":  {"primary": "#3A3A50", "secondary": "#1A1A30", "glow": "#3A3A5020"},
    }


# ─────────────────────────────────────────────────────────────────────────
# PARTICLE ORB VISUALIZER
# ─────────────────────────────────────────────────────────────────────────

class Particle:
    """A single particle orbiting the central orb."""
    __slots__ = ('angle', 'radius', 'speed', 'size', 'base_radius', 'phase',
                 'canvas_id', 'brightness')

    def __init__(self, base_radius, speed_range=(0.3, 1.5)):
        self.angle = random.uniform(0, 2 * math.pi)
        self.base_radius = base_radius + random.uniform(-15, 15)
        self.radius = self.base_radius
        self.speed = random.uniform(*speed_range) * random.choice([1, -1])
        self.size = random.uniform(1.0, 3.0)
        self.phase = random.uniform(0, 2 * math.pi)
        self.brightness = random.uniform(0.3, 1.0)
        self.canvas_id = None


class ParticleOrbVisualizer:
    """
    Multi-layered particle orb visualizer.
    
    Layers:
      1. Background glow (radial gradient via concentric circles)
      2. Orbiting particle rings (3 rings at different radii)
      3. Inner core (pulsing circle)
      4. Ripple waveforms (expanding circles when speaking)
    """

    def __init__(self, canvas):
        self.canvas = canvas
        self.particles = []
        self.glow_ids = []
        self.core_ids = []
        self.ripple_ids = []
        self.ring_ids = []
        self.cx = 0
        self.cy = 0
        self.t = 0.0
        self.state = "idle"
        self._initialized = False

        # Ripple state
        self.ripples = []  # List of {'radius': float, 'alpha': float, 'canvas_id': int}

    def setup(self, width, height):
        """Initialize all visual elements. Call once after canvas is visible."""
        self.cx = width / 2
        self.cy = height / 2
        self._initialized = True

        # ── Layer 1: Background Glow (concentric circles) ──
        self.glow_ids = []
        for i in range(25):
            r = 150 - i * 5
            if r <= 0:
                continue
            cid = self.canvas.create_oval(
                self.cx - r, self.cy - r, self.cx + r, self.cy + r,
                fill="", outline="", width=0
            )
            self.glow_ids.append(cid)

        # ── Layer 2: Orbital Rings (thin decorative rings) ──
        self.ring_ids = []
        for i in range(6):
            cid = self.canvas.create_oval(0, 0, 0, 0, fill="", outline="", width=1)
            self.ring_ids.append({
                "id": cid,
                "base_radius": 50 + i * 22,
                "speed": (0.4 + i * 0.15) * (1 if i % 2 == 0 else -1),
                "tilt_phase": i * 0.5,
            })

        # ── Layer 3: Particles (3 orbital belts) ──
        belt_configs = [
            {"count": 30, "radius": 60,  "speed": (0.5, 1.2)},
            {"count": 25, "radius": 95,  "speed": (0.3, 0.9)},
            {"count": 20, "radius": 130, "speed": (0.2, 0.7)},
        ]
        self.particles = []
        for belt in belt_configs:
            for _ in range(belt["count"]):
                p = Particle(belt["radius"], belt["speed"])
                p.canvas_id = self.canvas.create_oval(0, 0, 0, 0, fill="", outline="")
                self.particles.append(p)

        # ── Layer 4: Core (concentric filled circles for glow effect) ──
        self.core_ids = []
        for i in range(12):
            cid = self.canvas.create_oval(0, 0, 0, 0, fill="", outline="", width=0)
            self.core_ids.append(cid)

    def _hex_blend(self, color1, color2, factor):
        """Blend two hex colors. factor=0 → color1, factor=1 → color2."""
        r1, g1, b1 = int(color1[1:3], 16), int(color1[3:5], 16), int(color1[5:7], 16)
        r2, g2, b2 = int(color2[1:3], 16), int(color2[3:5], 16), int(color2[5:7], 16)
        r = int(r1 + (r2 - r1) * factor)
        g = int(g1 + (g2 - g1) * factor)
        b = int(b1 + (b2 - b1) * factor)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _hex_alpha(self, hex_color, alpha):
        """Dim a hex color by alpha (0.0 → black, 1.0 → original)."""
        r = int(int(hex_color[1:3], 16) * alpha)
        g = int(int(hex_color[3:5], 16) * alpha)
        b = int(int(hex_color[5:7], 16) * alpha)
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        return f"#{r:02x}{g:02x}{b:02x}"

    def update(self, width, height, state, dt):
        """Update all visual layers. Called every frame (~60fps)."""
        if not self._initialized:
            return

        self.cx = width / 2
        self.cy = height / 2
        self.t += dt
        self.state = state

        colors = DesignTokens.STATE_COLORS.get(state, DesignTokens.STATE_COLORS["idle"])
        primary = colors["primary"]
        secondary = colors["secondary"]

        # ── State-dependent physics ──
        if state == "speaking":
            spin_mult = 2.5
            pulse_amp = 18.0
            pulse_speed = 3.0
            core_size = 30
            glow_intensity = 0.6
        elif state == "thinking":
            spin_mult = 3.5
            pulse_amp = 8.0
            pulse_speed = 5.0
            core_size = 25
            glow_intensity = 0.5
        elif state == "listening":
            spin_mult = 1.0
            pulse_amp = 5.0
            pulse_speed = 1.5
            core_size = 28
            glow_intensity = 0.45
        else:  # idle / sleeping
            spin_mult = 0.4
            pulse_amp = 2.0
            pulse_speed = 0.8
            core_size = 22
            glow_intensity = 0.25

        # ── Update Background Glow ──
        for i, gid in enumerate(self.glow_ids):
            norm = i / max(len(self.glow_ids) - 1, 1)
            r = 150 - i * 5
            pulse = math.sin(self.t * pulse_speed + i * 0.1) * pulse_amp * 0.3
            r += pulse
            if r <= 0:
                self.canvas.itemconfig(gid, fill="", outline="")
                continue
            alpha = glow_intensity * (1.0 - norm) * (0.7 + 0.3 * math.sin(self.t * 1.5 + i * 0.2))
            color = self._hex_alpha(primary, alpha * 0.15)
            self.canvas.itemconfig(gid, fill=color, outline="")
            self.canvas.coords(gid,
                               self.cx - r, self.cy - r,
                               self.cx + r, self.cy + r)

        # ── Update Orbital Rings ──
        for ring in self.ring_ids:
            rid = ring["id"]
            tilt = math.sin(self.t * 1.2 * spin_mult + ring["tilt_phase"])
            pulse = math.sin(self.t * pulse_speed + ring["base_radius"] * 0.02) * pulse_amp * 0.5
            r = ring["base_radius"] + pulse
            aspect = 0.5 + 0.5 * abs(tilt)
            rx = r
            ry = r * aspect

            alpha = 0.15 + 0.15 * abs(tilt)
            color = self._hex_alpha(primary, alpha)
            width = 1.0 + abs(tilt) * 1.5

            self.canvas.itemconfig(rid, outline=color, width=width)
            self.canvas.coords(rid,
                               self.cx - rx, self.cy - ry,
                               self.cx + rx, self.cy + ry)

        # ── Update Particles ──
        for p in self.particles:
            p.angle += p.speed * spin_mult * dt
            pulse = math.sin(self.t * pulse_speed + p.phase) * pulse_amp
            p.radius = p.base_radius + pulse

            x = self.cx + math.cos(p.angle) * p.radius
            y = self.cy + math.sin(p.angle) * p.radius * 0.6  # 3D perspective

            # Brightness flicker
            flicker = 0.6 + 0.4 * math.sin(self.t * 2.5 + p.phase)
            alpha = p.brightness * flicker * glow_intensity * 2.0
            alpha = min(1.0, max(0.05, alpha))

            color = self._hex_alpha(primary, alpha)
            sz = p.size * (0.8 + 0.4 * math.sin(self.t * 1.5 + p.phase))

            self.canvas.itemconfig(p.canvas_id, fill=color, outline=color)
            self.canvas.coords(p.canvas_id,
                               x - sz, y - sz,
                               x + sz, y + sz)

        # ── Update Core ──
        for i, cid in enumerate(self.core_ids):
            norm = i / max(len(self.core_ids) - 1, 1)
            pulse = math.sin(self.t * pulse_speed) * pulse_amp * 0.3
            r = core_size * (1.0 - norm * 0.7) + pulse * (1.0 - norm)

            if r <= 0:
                self.canvas.itemconfig(cid, fill="", outline="")
                continue

            alpha = (1.0 - norm) * 0.9
            if norm < 0.3:
                color = self._hex_blend("#FFFFFF", primary, norm / 0.3)
            else:
                color = self._hex_alpha(primary, alpha)

            self.canvas.itemconfig(cid, fill=color, outline="")
            self.canvas.coords(cid,
                               self.cx - r, self.cy - r,
                               self.cx + r, self.cy + r)

        # ── Ripples (speaking state only) ──
        if state == "speaking":
            # Spawn a new ripple every ~0.4s
            if len(self.ripples) == 0 or (self.ripples and self.ripples[-1]["radius"] > 40):
                if len(self.ripples) < 5:
                    rid = self.canvas.create_oval(0, 0, 0, 0, fill="", outline="", width=2)
                    self.ripples.append({"radius": core_size, "alpha": 0.8, "id": rid})

        # Update existing ripples
        new_ripples = []
        for ripple in self.ripples:
            ripple["radius"] += 80 * dt
            ripple["alpha"] -= 0.6 * dt

            if ripple["alpha"] <= 0:
                self.canvas.delete(ripple["id"])
                continue

            r = ripple["radius"]
            color = self._hex_alpha(primary, max(0.01, ripple["alpha"] * 0.5))
            self.canvas.itemconfig(ripple["id"], outline=color, width=max(1, 2 * ripple["alpha"]))
            self.canvas.coords(ripple["id"],
                               self.cx - r, self.cy - r * 0.6,
                               self.cx + r, self.cy + r * 0.6)
            new_ripples.append(ripple)
        self.ripples = new_ripples

        # Clean up ripples when not speaking
        if state != "speaking" and self.ripples:
            for ripple in self.ripples:
                ripple["alpha"] -= 2.0 * dt
                if ripple["alpha"] <= 0:
                    self.canvas.delete(ripple["id"])
            self.ripples = [r for r in self.ripples if r["alpha"] > 0]


# ─────────────────────────────────────────────────────────────────────────
# VOICE OVERLAY FRAME
# ─────────────────────────────────────────────────────────────────────────

class VoiceOverlayFrame(ctk.CTkFrame):
    """
    Full-screen voice mode overlay.
    Shows the particle orb visualizer + state label + close button.
    """

    def __init__(self, master, close_callback, **kwargs):
        super().__init__(master, fg_color=DesignTokens.BG_PRIMARY,
                         corner_radius=0, **kwargs)
        self.close_callback = close_callback

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Canvas for the orb ──
        self.canvas = tk.Canvas(self, bg=DesignTokens.BG_PRIMARY,
                                highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        # ── Close Button ──
        self.close_btn = ctk.CTkButton(
            self, text="✕", width=44, height=44, corner_radius=22,
            command=self.close_callback,
            fg_color="#1A1A2E", hover_color="#2A2A44",
            text_color=DesignTokens.TEXT_DIM,
            font=("Segoe UI", 18, "bold"),
            border_width=1, border_color=DesignTokens.BORDER_GLASS
        )
        self.close_btn.place(relx=0.95, rely=0.04, anchor="ne")

        # ── Status Label ──
        self.status_label = ctk.CTkLabel(
            self, text="Listening...",
            font=DesignTokens.FONT_STATUS,
            text_color=DesignTokens.TEXT_PRIMARY
        )
        self.status_label.place(relx=0.5, rely=0.82, anchor="center")

        # ── Subtitle / User Speech ──
        self.subtitle_label = ctk.CTkLabel(
            self, text="",
            font=DesignTokens.FONT_BODY,
            text_color=DesignTokens.TEXT_DIM,
            wraplength=500
        )
        self.subtitle_label.place(relx=0.5, rely=0.88, anchor="center")

        # ── State Dot ──
        self.state_dot = ctk.CTkLabel(
            self, text="●", font=("Segoe UI", 10),
            text_color=DesignTokens.ACCENT_GREEN
        )
        self.state_dot.place(relx=0.5, rely=0.77, anchor="center")

        # ── Orb Visualizer ──
        self.orb = ParticleOrbVisualizer(self.canvas)
        self.state = "listening"
        self.running = False
        self.animation_id = None
        self.last_time = time.time()
        self._orb_setup_done = False

    def start_animation(self):
        """Begin the animation loop."""
        self.running = True
        self.last_time = time.time()
        # Defer orb setup until canvas has a real size
        self.after(50, self._deferred_start)

    def _deferred_start(self):
        """Setup orb after canvas has been laid out."""
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w > 1 and h > 1 and not self._orb_setup_done:
            self.orb.setup(w, h)
            self._orb_setup_done = True
        self.animate()

    def stop_animation(self):
        """Stop the animation loop."""
        self.running = False
        if self.animation_id:
            self.after_cancel(self.animation_id)
            self.animation_id = None

    def set_state(self, state):
        """Transition the visualizer to a new state."""
        self.state = state
        labels = {
            "listening": "Listening...",
            "thinking":  "Thinking...",
            "speaking":  "Speaking...",
            "sleeping":  "Tap mic to start",
            "idle":      "Ready"
        }
        self.status_label.configure(text=labels.get(state, "Ready"))
        self.subtitle_label.configure(text="")

        # Update state dot color
        colors = DesignTokens.STATE_COLORS.get(state, DesignTokens.STATE_COLORS["idle"])
        self.state_dot.configure(text_color=colors["primary"])

    def set_text(self, text):
        """Display recognized speech or AI response text."""
        if len(text) > 80:
            text = text[:77] + "..."
        self.subtitle_label.configure(text=text)

    def animate(self):
        """Main animation loop — targets ~60fps."""
        if not self.running:
            return

        now = time.time()
        dt = now - self.last_time
        self.last_time = now

        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()

        if w > 1 and h > 1:
            self.orb.update(w, h, self.state, dt)

        self.animation_id = self.after(16, self.animate)  # ~60fps


# ─────────────────────────────────────────────────────────────────────────
# GLASSMORPHISM MESSAGE BUBBLE
# ─────────────────────────────────────────────────────────────────────────

class GlassMessageBubble(ctk.CTkFrame):
    """
    A styled chat message bubble with glassmorphism effect.
    Supports sender types: 'You', 'AI', 'System'.
    """

    def __init__(self, master, sender, message, **kwargs):
        # Determine styling based on sender
        if sender == "You":
            fg = "#0D2847"
            border_color = "#1E4D8C"
            text_color = "#B0D4FF"
            anchor = "e"
            padx_outer = (60, 12)
        elif sender == "System":
            fg = "#1A1A2A"
            border_color = DesignTokens.BORDER_GLASS
            text_color = DesignTokens.TEXT_DIM
            anchor = "center"
            padx_outer = (50, 50)
        else:  # AI
            fg = DesignTokens.BG_GLASS
            border_color = "#2A1A4A"
            text_color = DesignTokens.TEXT_PRIMARY
            anchor = "w"
            padx_outer = (12, 60)

        super().__init__(
            master, corner_radius=DesignTokens.CORNER_SM,
            fg_color=fg, border_width=1, border_color=border_color,
            **kwargs
        )

        # ── Sender Label ──
        if sender != "System":
            sender_text = sender if sender == "You" else "Telex"
            sender_color = DesignTokens.ACCENT_BLUE if sender == "You" else DesignTokens.ACCENT_PURPLE
            sender_label = ctk.CTkLabel(
                self, text=sender_text,
                font=DesignTokens.FONT_LABEL,
                text_color=sender_color
            )
            sender_label.pack(padx=12, pady=(8, 0), anchor="w")

        # ── Message Text ──
        msg_font = DesignTokens.FONT_BODY if sender != "System" else ("Segoe UI", 11, "italic")
        message_label = ctk.CTkLabel(
            self, text=message,
            wraplength=420,
            justify="left",
            font=msg_font,
            text_color=text_color
        )
        message_label.pack(padx=12, pady=(4, 10) if sender != "System" else (6, 6))

        # Pack with alignment
        self.pack(pady=4, padx=padx_outer, anchor=anchor)


# ─────────────────────────────────────────────────────────────────────────
# HEADER BAR
# ─────────────────────────────────────────────────────────────────────────

class HeaderBar(ctk.CTkFrame):
    """Top bar with app title, status indicator, and accent styling."""

    def __init__(self, master, **kwargs):
        super().__init__(master, height=56, corner_radius=0,
                         fg_color=DesignTokens.BG_SURFACE,
                         border_width=0, **kwargs)
        self.pack_propagate(False)

        # ── Inner container ──
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=8)

        # ── App Title ──
        self.title_label = ctk.CTkLabel(
            inner, text="T E L E X",
            font=("Consolas", 20, "bold"),
            text_color=DesignTokens.ACCENT_CYAN
        )
        self.title_label.pack(side="left")

        # ── Subtitle ──
        self.subtitle = ctk.CTkLabel(
            inner, text="AI COMPANION",
            font=DesignTokens.FONT_MONO_SM,
            text_color=DesignTokens.TEXT_DIM
        )
        self.subtitle.pack(side="left", padx=(12, 0))

        # ── Status Indicator (right side) ──
        self.status_frame = ctk.CTkFrame(inner, fg_color="transparent")
        self.status_frame.pack(side="right")

        self.status_dot = ctk.CTkLabel(
            self.status_frame, text="●", font=("Segoe UI", 8),
            text_color=DesignTokens.TEXT_DIM
        )
        self.status_dot.pack(side="left", padx=(0, 6))

        self.status_text = ctk.CTkLabel(
            self.status_frame, text="Loading...",
            font=DesignTokens.FONT_MONO_SM,
            text_color=DesignTokens.TEXT_DIM
        )
        self.status_text.pack(side="left")

        # ── Bottom border glow ──
        self.border_line = ctk.CTkFrame(
            self, height=1, corner_radius=0,
            fg_color=DesignTokens.BORDER_GLASS
        )
        self.border_line.pack(side="bottom", fill="x")

    def set_status(self, text, color=None):
        """Update the status indicator."""
        self.status_text.configure(text=text)
        if color:
            self.status_dot.configure(text_color=color)
            self.status_text.configure(text_color=color)


# ─────────────────────────────────────────────────────────────────────────
# CONTROL DOCK (Input Bar)
# ─────────────────────────────────────────────────────────────────────────

class ControlDock(ctk.CTkFrame):
    """
    Bottom control bar with mic button, text input, and send button.
    Glassmorphism styling with glowing accents.
    """

    def __init__(self, master, mic_callback, send_callback, **kwargs):
        super().__init__(master, height=70, corner_radius=0,
                         fg_color=DesignTokens.BG_SURFACE,
                         border_width=0, **kwargs)
        self.pack_propagate(False)
        self.mic_callback = mic_callback
        self.send_callback = send_callback

        # ── Top border glow ──
        self.border_line = ctk.CTkFrame(
            self, height=1, corner_radius=0,
            fg_color=DesignTokens.BORDER_GLASS
        )
        self.border_line.pack(side="top", fill="x")

        # ── Inner container ──
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=10)
        inner.grid_columnconfigure(1, weight=1)

        # ── Mic Button ──
        self.mic_button = ctk.CTkButton(
            inner, text="🎤", width=48, height=48,
            corner_radius=24,
            command=self.mic_callback,
            fg_color="#1A1A3A",
            hover_color="#2A2A50",
            border_width=2,
            border_color=DesignTokens.ACCENT_CYAN,
            font=("Segoe UI", 20),
            text_color=DesignTokens.ACCENT_CYAN
        )
        self.mic_button.grid(row=0, column=0, padx=(0, 10))

        # ── Text Entry ──
        self.entry = ctk.CTkEntry(
            inner, height=44,
            placeholder_text="Type your message...",
            placeholder_text_color=DesignTokens.TEXT_DIM,
            font=DesignTokens.FONT_BODY,
            fg_color=DesignTokens.BG_INPUT,
            border_width=1,
            border_color=DesignTokens.BORDER_GLASS,
            corner_radius=DesignTokens.CORNER_SM,
            text_color=DesignTokens.TEXT_PRIMARY
        )
        self.entry.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.entry.bind("<Return>", self.send_callback)

        # ── Send Button ──
        self.send_button = ctk.CTkButton(
            inner, text="➤", width=48, height=44,
            corner_radius=DesignTokens.CORNER_SM,
            command=self.send_callback,
            fg_color="#1A1A3A",
            hover_color="#0D2847",
            border_width=1,
            border_color=DesignTokens.ACCENT_BLUE,
            font=("Segoe UI", 18),
            text_color=DesignTokens.ACCENT_BLUE
        )
        self.send_button.grid(row=0, column=2)

    def set_mic_state(self, state):
        """Update mic button appearance based on voice state."""
        colors = DesignTokens.STATE_COLORS.get(state, DesignTokens.STATE_COLORS["idle"])
        if state == "listening":
            self.mic_button.configure(
                text="◉", fg_color="#0A2A1A",
                border_color=colors["primary"],
                text_color=colors["primary"],
                hover_color="#0F3A25"
            )
        elif state in ("thinking", "speaking"):
            self.mic_button.configure(
                text="◉", fg_color="#1A0A2A",
                border_color=colors["primary"],
                text_color=colors["primary"],
                hover_color="#2A1A40"
            )
        else:
            self.mic_button.configure(
                text="🎤", fg_color="#1A1A3A",
                border_color=DesignTokens.ACCENT_CYAN,
                text_color=DesignTokens.ACCENT_CYAN,
                hover_color="#2A2A50"
            )

    def toggle_inputs(self, state):
        """Enable or disable input controls."""
        self.entry.configure(state=state)
        self.send_button.configure(state=state)

    def get_text(self):
        """Get the current entry text."""
        return self.entry.get().strip()

    def clear_text(self):
        """Clear the entry field."""
        self.entry.delete(0, tk.END)


# ─────────────────────────────────────────────────────────────────────────
# CHAT APPLICATION (Main Controller)
# ─────────────────────────────────────────────────────────────────────────

class ChatApplication:
    """
    Main application controller. 
    
    Public API (unchanged):
      __init__(root, voice_handler, chat_logic)
      set_llm_handler(llm_handler)
      toggle_voice_mode()
      send_message(event=None, text=None)
      display_message(sender, message)
    """

    def __init__(self, root, voice_handler, chat_logic):
        self.root = root
        self.voice_handler = voice_handler
        self.chat_logic = chat_logic
        self.llm_handler = None

        # Connect Voice Handler Callbacks
        self.voice_handler.set_interruption_callback(self.handle_interruption)
        self.voice_handler.set_speech_end_callback(self.handle_speech_end)

        self.voice_mode_active = False

        # ── Window Setup ──
        self.root.title("Telex — AI Companion")
        self.root.geometry("680x780")
        self.root.minsize(500, 600)
        self.root.configure(fg_color=DesignTokens.BG_PRIMARY)

        # Grid layout for root
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)  # Chat area expands

        # ── Build the UI ──
        self._build_ui()

        # ── Entrance Animation ──
        self._play_entrance_animation()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _build_ui(self):
        """Construct all UI components."""

        # ── Header Bar ──
        self.header = HeaderBar(self.root)
        self.header.grid(row=0, column=0, sticky="ew")
        # Start hidden for entrance animation
        self.header.grid_remove()

        # ── Main Chat Frame (contains scrollable chat) ──
        self.main_frame = ctk.CTkFrame(
            self.root, corner_radius=0,
            fg_color=DesignTokens.BG_PRIMARY
        )
        self.main_frame.grid(row=1, column=0, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)
        # Start hidden for entrance animation
        self.main_frame.grid_remove()

        # ── Scrollable Chat History ──
        self.chat_history_frame = ctk.CTkScrollableFrame(
            self.main_frame,
            corner_radius=0,
            fg_color=DesignTokens.BG_PRIMARY,
            scrollbar_button_color=DesignTokens.BORDER_GLASS,
            scrollbar_button_hover_color=DesignTokens.ACCENT_CYAN,
            label_text=""
        )
        self.chat_history_frame.grid(row=0, column=0, padx=8, pady=(4, 4), sticky="nsew")
        self.chat_history_frame.grid_columnconfigure(0, weight=1)

        # ── Control Dock (bottom bar) ──
        self.dock = ControlDock(
            self.root,
            mic_callback=self.toggle_voice_mode,
            send_callback=self.send_message
        )
        self.dock.grid(row=2, column=0, sticky="ew")
        # Start hidden for entrance animation
        self.dock.grid_remove()

        # ── Voice Overlay (hidden by default) ──
        self.voice_overlay = VoiceOverlayFrame(
            self.root, close_callback=self.toggle_voice_mode
        )

    # ─────────────────────────────────────────────────────────────────
    # ENTRANCE ANIMATION
    # ─────────────────────────────────────────────────────────────────

    def _play_entrance_animation(self):
        """Staggered reveal of UI components on launch."""
        # Step 1: Show header (after 300ms)
        self.root.after(300, self._reveal_header)
        # Step 2: Show chat (after 600ms)
        self.root.after(600, self._reveal_chat)
        # Step 3: Show dock (after 900ms)
        self.root.after(900, self._reveal_dock)
        # Step 4: Welcome message (after 1200ms)
        self.root.after(1200, self._show_welcome)

    def _reveal_header(self):
        self.header.grid()

    def _reveal_chat(self):
        self.main_frame.grid()

    def _reveal_dock(self):
        self.dock.grid()

    def _show_welcome(self):
        self.display_message("System",
                             "⚡ Systems online. Click 🎤 for Voice Mode or type below.")

    # ─────────────────────────────────────────────────────────────────
    # VOICE MODE
    # ─────────────────────────────────────────────────────────────────

    def toggle_voice_mode(self):
        """Toggle between chat mode and voice mode."""
        if self.voice_mode_active:
            # ── Turn OFF Voice Mode ──
            self.voice_mode_active = False
            self.voice_overlay.stop_animation()
            self.voice_overlay.grid_forget()

            # Show chat UI
            self.header.grid()
            self.main_frame.grid()
            self.dock.grid()

            self.dock.set_mic_state("idle")
            self.dock.toggle_inputs('normal')
            self.display_message("System", "Voice Mode deactivated.")
        else:
            # ── Turn ON Voice Mode ──
            self.voice_mode_active = True

            # Hide chat UI
            self.header.grid_remove()
            self.main_frame.grid_remove()
            self.dock.grid_remove()

            # Show voice overlay
            self.voice_overlay.grid(row=0, column=0, rowspan=3, sticky="nsew")
            self.voice_overlay.start_animation()
            self.voice_overlay.set_state("listening")

            self.dock.set_mic_state("listening")
            self.display_message("System", "Voice Mode activated.")
            self.start_listening()

    # ─────────────────────────────────────────────────────────────────
    # VOICE CALLBACKS
    # ─────────────────────────────────────────────────────────────────

    def start_listening(self):
        """Begin listening for user speech."""
        if not self.voice_mode_active:
            return
        print("UI: Starting to listen...")
        self.voice_overlay.set_state("listening")
        self.dock.set_mic_state("listening")
        self.voice_handler.listen(self.handle_recognized_text)

    def handle_speech_end(self):
        """Called when the AI finishes speaking."""
        self.root.after(0, self.process_speech_end)

    def process_speech_end(self):
        if self.voice_mode_active:
            print("UI: Speech ended. Looping to listen again.")
            self.start_listening()
        else:
            print("UI: Speech ended. Voice mode off, not looping.")
            self.dock.set_mic_state("idle")

    def handle_recognized_text(self, text):
        """Called with recognized speech text (from voice_handler)."""
        self.root.after(0, self.process_recognized_text, text)

    def process_recognized_text(self, text):
        if not self.voice_mode_active:
            self.dock.toggle_inputs('normal')
            self.dock.set_mic_state("idle")
            return

        if "[ERROR]" not in text and "[SYSTEM]" not in text:
            # Transition to Thinking state
            self.voice_overlay.set_state("thinking")
            self.voice_overlay.set_text(f'"{text}"')
            self.dock.set_mic_state("thinking")
            self.send_message(text=text)
        else:
            self.display_message("System", text)
            self.start_listening()

    def handle_interruption(self, text):
        """Called when user interrupts the AI mid-speech."""
        self.root.after(0, self.process_interruption_text, text)

    def process_interruption_text(self, text):
        if not self.voice_mode_active:
            return

        if "[ERROR]" not in text:
            self.voice_overlay.set_state("thinking")
            self.voice_overlay.set_text(f'"{text}"')
            self.dock.set_mic_state("thinking")
            self.send_message(text=text)
        else:
            self.display_message("System", text)
            self.start_listening()

    # ─────────────────────────────────────────────────────────────────
    # MESSAGING
    # ─────────────────────────────────────────────────────────────────

    def send_message(self, event=None, text=None):
        """Send a message (from text input or voice recognition)."""
        if self.llm_handler is None:
            self.display_message("System",
                                 "⏳ The AI model is still loading. Please wait.")
            return

        user_input = ""
        if text:
            user_input = text
        else:
            user_input = self.dock.get_text()

        if not user_input:
            if self.voice_mode_active:
                self.start_listening()
            return

        print("\n" + "═" * 50)
        print(f"You: {user_input}")
        self.display_message("You", user_input)
        self.dock.clear_text()

        if not self.voice_mode_active:
            self.dock.toggle_inputs('disabled')

        self.chat_logic.add_user_message(user_input)
        threading.Thread(target=self.process_response,
                         args=(user_input,), daemon=True).start()

    def process_response(self, user_query):
        """Process the AI response in a background thread."""
        # Use the correct method from ChatLogic
        try:
            history = self.chat_logic.get_full_history_with_memory(user_query)
        except Exception as e:
            print(f"Memory recall failed, falling back: {e}")
            history = self.chat_logic.conversation_history.copy()

        ai_message = self.llm_handler.get_response(history)

        # FIX: add_ai_message takes only 1 argument (ai_response)
        self.chat_logic.add_ai_message(ai_message)
        self.root.after(0, self.display_ai_message, ai_message)

    def display_ai_message(self, ai_message):
        """Display the AI's response and optionally speak it."""
        if not ai_message.strip():
            print("AI: [Chose to say nothing]")
            if self.voice_mode_active:
                self.start_listening()
            else:
                self.dock.toggle_inputs('normal')
                self.dock.entry.focus_set()
            return

        print(f"AI: {ai_message}")
        print("═" * 50 + "\n")
        self.display_message("AI", ai_message)

        if self.voice_mode_active:
            # Set overlay to speaking state
            self.voice_overlay.set_state("speaking")
            self.voice_overlay.set_text(ai_message)
            self.dock.set_mic_state("speaking")
            self.voice_handler.speak_with_barge_in(ai_message)
        else:
            self.voice_handler.speak_silently(ai_message)
            self.dock.toggle_inputs('normal')
            self.dock.entry.focus_set()

    # ─────────────────────────────────────────────────────────────────
    # INPUT CONTROL
    # ─────────────────────────────────────────────────────────────────

    def toggle_inputs(self, state):
        """Enable/disable text input controls."""
        self.dock.toggle_inputs(state)
        if self.voice_mode_active:
            self.dock.mic_button.configure(state='normal')
        else:
            self.dock.mic_button.configure(state=state)

    # ─────────────────────────────────────────────────────────────────
    # DISPLAY
    # ─────────────────────────────────────────────────────────────────

    def display_message(self, sender, message):
        """Add a styled message bubble to the chat history."""
        GlassMessageBubble(self.chat_history_frame, sender, message)

        # Auto-scroll to bottom
        self.root.update_idletasks()
        if hasattr(self.chat_history_frame, "_parent_canvas"):
            self.chat_history_frame._parent_canvas.yview_moveto(1.0)

    # ─────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ─────────────────────────────────────────────────────────────────

    def set_llm_handler(self, llm_handler):
        """Called when the LLM finishes loading."""
        self.llm_handler = llm_handler
        self.header.set_status("Online", DesignTokens.ACCENT_GREEN)
        self.display_message("AI",
                             "Alright, I'm here. What's the plan? 😉")

    def on_closing(self):
        """Clean shutdown."""
        print("\n--- End of Session ---")
        try:
            self.voice_overlay.stop_animation()
        except Exception:
            pass
        self.chat_logic.close()
        self.root.destroy()