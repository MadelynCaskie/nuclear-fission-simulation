"""
Nuclear Fission Chain Reaction Simulation
Requires: pygame  (pip install pygame)

All UI stats are driven entirely by real-time particle dynamics:

  k-effective      — neutron population ratio across 60-frame generation windows
  Neutron flux     — core particle density × mean neutron speed (n/cm^2/s)
  Fission cross-section — drops with fuel temperature via Doppler 1/v law and
                          directly resizes the collision hitboxes on fuel rods
  Temperatures     — separate fuel-centerline and coolant temperatures coupled
                     by a heat-transfer equation. Each fission event heats the
                     fuel, which conducts to the coolant, which the external
                     loop cools back toward the inlet temperature

Controls:
  Click inside reactor  — inject a neutron
  R                     — restart
  P                     — pause / unpause
  Q / ESC               — quit
"""

import sys, math, random

try:
    import pygame
except ImportError:
    sys.exit("pygame required:  pip install pygame")

# Window 
WIDTH, HEIGHT = 1150, 800
FPS = 60

# Reactor geometry 
CX, CY      = 430, 408
CORE_R      = 128   # px — hex fuel cluster fits inside this circle
HOT_R       = 162   # px — hot-coolant zone outer edge
VESSEL_IN   = 258   # px — inner vessel wall (neutrons reflect here)
VESSEL_OUT  = 308   # px — outer vessel wall

# Hex fuel grid 
HEX_SPACE   = 18    # px, centre-to-centre
ATOM_R      = 6     # px, visual rod radius

# Neutron motion 
NEUTRON_R        = 3
NEUTRON_SPEED    = 3.5      # px / frame (base)
INITIAL_NEUTRONS = 3
MAX_NEUTRONS     = 500
TRAIL_LEN        = 10

# Cross-section physics (Doppler 1/v law) 
SIGMA_0   = 585.0   # U-235 thermal fission cross-section at T_REF (barns)
T_REF_K   = 293.15  # reference temperature (20 Degrees C in Kelvin)
# Base collision radius (at cold conditions).  Actual coll_r is derived
# from sigma each frame, so this sets the room-temperature upper bound.
BASE_COLL_R = 11.0  # px

# Thermodynamics 
T_INLET          = 287.0   # Degrees C — PWR cold-leg inlet coolant temperature
HEAT_PER_FISSION = 2.0     # Degrees C added to fuel centreline per fission event
FUEL_COOLANT_K   = 0.015   # conduction coefficient (fuel → coolant, /frame)
COOLANT_DECAY    = 0.30    # fraction of (T_coolant − T_inlet) removed /frame
FUEL_RADIATION   = 0.002   # supplemental fuel → coolant radiation (/frame)
T_FUEL_MAX       = 1400.0  # Degrees C — UO2 melting-point margin (display ceiling)

# ── Control rods 
CONTROL_TARGET_N    = 80    # target neutron population inside vessel
CONTROL_SENSITIVITY = 0.012 # rod insertion rate per excess neutron
CONTROL_MAX_ABSORB  = 0.55  # max fraction of excess neutrons absorbed / frame

# k-effective tracking 
K_CYCLE_FRAMES = 60

#  Neutron flux calibration 
# Physical core radius for density calculation
CORE_R_CM      = 120.0                          # cm
CORE_AREA_CM2  = math.pi * CORE_R_CM ** 2      # ≈ 45 239 cm^2
PX_PER_CM      = CORE_R / CORE_R_CM            # pixels per centimetre
# At target population and base speed, calibrate to 5×10^12 n/cm^2/s (startup power)
_ref_density   = CONTROL_TARGET_N / CORE_AREA_CM2
_ref_speed_cms = NEUTRON_SPEED / PX_PER_CM * FPS
FLUX_SCALE     = 5.0e12 / max(_ref_density * _ref_speed_cms, 1e-30)

# Colour palette 
C_BG          = (42,  82, 112)
C_VESSEL_FILL = (16,  22,  44)
C_VESSEL_EDGE = (52,  75, 145)
C_MOD         = (26,  34,  88)
C_MOD_LINE    = (40,  54, 118)
C_HOT_COOL    = (182,  48,   8)   # hot-coolant at cold conditions
C_HOT_HOT     = (255, 115,  12)   # hot-coolant at peak coolant temp
C_CORE_COOL   = ( 88,  20,   4)   # core bg at cold fuel
C_CORE_HOT    = (160,  44,   6)   # core bg at hot fuel
C_FUEL_OUT    = ( 20,  72,  26)
C_FUEL_MID    = ( 50, 140,  58)
C_FUEL_CTR    = ( 28,  58,  30)
C_FUEL_SPENT  = ( 28,  36,  28)
C_NEUTRON     = (255, 248, 108)
C_UI          = (208, 214, 235)
C_DIM         = (108, 114, 145)
C_BAR_BG      = ( 20,  25,  48)
C_BAR_BORDER  = ( 52,  62, 108)
C_PANEL_BG    = ( 13,  17,  38)
C_PANEL_EDGE  = ( 44,  54, 100)


def lerp(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def fmt_flux(flux):
    """Format flux as X.X×10ⁿ n/cm²/s using Unicode superscripts."""
    if flux < 1.0:
        return "< 10⁰ n/cm²/s"
    exp  = int(math.floor(math.log10(flux)))
    mant = flux / (10 ** exp)
    sup  = str(exp).translate(str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹"))
    return f"{mant:.2f}×10{sup} n/cm²/s"


# FuelAtom
class FuelAtom:
    """U-235 fuel rod (cross-section view)."""

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.active = True

    def draw(self, surf):
        ix, iy = int(self.x), int(self.y)
        if self.active:
            pygame.draw.circle(surf, C_FUEL_OUT, (ix, iy), ATOM_R)
            pygame.draw.circle(surf, C_FUEL_MID, (ix, iy), ATOM_R - 2)
            pygame.draw.circle(surf, C_FUEL_CTR, (ix, iy), max(1, ATOM_R - 4))
        else:
            pygame.draw.circle(surf, C_FUEL_SPENT, (ix, iy), ATOM_R - 1)


def build_hex_fuel():
    """Generate FuelAtom positions in a circular hex-packed cluster."""
    atoms = []
    n = int(CORE_R / HEX_SPACE) + 2
    for q in range(-n, n + 1):
        for r in range(-n, n + 1):
            if abs(-q - r) > n:
                continue
            x = HEX_SPACE * (math.sqrt(3) * q + math.sqrt(3) / 2 * r)
            y = HEX_SPACE * (3.0 / 2 * r)
            if math.hypot(x, y) < CORE_R - ATOM_R:
                atoms.append(FuelAtom(CX + x, CY + y))
    return atoms


# Neutron 
class Neutron:
    def __init__(self, x, y, vx=None, vy=None):
        self.x = x
        self.y = y
        ang = random.uniform(0, 2 * math.pi)
        spd = NEUTRON_SPEED * random.uniform(0.85, 1.2)
        self.vx = vx if vx is not None else math.cos(ang) * spd
        self.vy = vy if vy is not None else math.sin(ang) * spd
        self.alive = True
        self.trail = []

    def update(self):
        self.trail.append((self.x, self.y))
        if len(self.trail) > TRAIL_LEN:
            self.trail.pop(0)
        self.x += self.vx
        self.y += self.vy
        # Reflect off inner vessel wall
        dx = self.x - CX
        dy = self.y - CY
        dist = math.hypot(dx, dy)
        if dist >= VESSEL_IN - 1:
            nx = dx / dist
            ny = dy / dist
            dot = self.vx * nx + self.vy * ny
            self.vx -= 2 * dot * nx
            self.vy -= 2 * dot * ny
            self.x = CX + nx * (VESSEL_IN - 2)
            self.y = CY + ny * (VESSEL_IN - 2)

    def draw(self, surf):
        n = len(self.trail)
        for i, (tx, ty) in enumerate(self.trail):
            fade = int(150 * i / max(n, 1))
            pygame.draw.circle(surf, (fade, fade, 25),
                               (int(tx), int(ty)), max(1, NEUTRON_R - 1))
        pygame.draw.circle(surf, C_NEUTRON, (int(self.x), int(self.y)), NEUTRON_R)


#  Fission flash 
class Flash:
    LT = 20
    MR = 22

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.lt = self.LT

    @property
    def alive(self):
        return self.lt > 0

    def update(self):
        self.lt -= 1

    def draw(self, surf):
        t = self.lt / self.LT
        r = int(self.MR * (1 - t))
        if r < 1:
            return
        color = lerp((255, 80, 10), (255, 240, 70), t)
        pygame.draw.circle(surf, color, (int(self.x), int(self.y)), r, 2)
        if t > 0.5:
            pygame.draw.circle(surf, (255, 255, 200),
                               (int(self.x), int(self.y)), max(1, r // 3))


# ── Reactor cross-section drawing ─────────────────────────────────────────────
def draw_reactor(surf, tr_cool, tr_fuel):
    """
    Concentric zones, outermost first.
    tr_cool: coolant temp ratio 0-1  (drives hot-coolant ring colour)
    tr_fuel: fuel temp ratio 0-1     (drives core background colour)
    """
    pygame.draw.circle(surf, C_VESSEL_FILL, (CX, CY), VESSEL_OUT)
    pygame.draw.circle(surf, C_MOD,         (CX, CY), VESSEL_IN)

    for rad in range(int(HOT_R) + 8, int(VESSEL_IN) - 2, 6):
        pygame.draw.circle(surf, C_MOD_LINE, (CX, CY), rad, 1)

    pygame.draw.circle(surf, C_VESSEL_EDGE, (CX, CY), VESSEL_IN, 3)
    pygame.draw.circle(surf, lerp(C_VESSEL_EDGE, (200, 220, 255), 0.25),
                       (CX, CY), VESSEL_OUT, 2)

    hot_col  = lerp(C_HOT_COOL, C_HOT_HOT, tr_cool)
    pygame.draw.circle(surf, hot_col, (CX, CY), HOT_R)

    core_col = lerp(C_CORE_COOL, C_CORE_HOT, tr_fuel)
    pygame.draw.circle(surf, core_col, (CX, CY), CORE_R)


# ── Simulation ────────────────────────────────────────────────────────────────
class Simulation:

    def __init__(self):
        pygame.init()
        self.screen  = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption(
            "U-235 Chain Reaction  |  Click=Neutron  R=Restart  P=Pause  Q=Quit")
        self.clock   = pygame.time.Clock()
        self.fsm     = pygame.font.SysFont("monospace", 12)
        self.fmd     = pygame.font.SysFont("monospace", 14, bold=True)
        self.flg     = pygame.font.SysFont("monospace", 18, bold=True)
        self.running = True
        self.paused  = False
        self._reset()

    # ── Setup ──────────────────────────────────────────────────────────────────

    def _reset(self):
        # Temperatures (physical, °C)
        self.fuel_temp    = T_INLET   # fuel-rod centreline
        self.coolant_temp = T_INLET   # bulk coolant

        # Cross-section and hitbox (derived from fuel_temp each frame)
        self.sigma  = SIGMA_0
        self.coll_r = BASE_COLL_R

        # Flux (n/cm²/s, computed from particle dynamics)
        self.neutron_flux = 0.0

        # k-effective (60-frame generation window)
        self.k_eff        = 1.0
        self._gen_frame   = 0
        self._gen_start_n = INITIAL_NEUTRONS

        # Control rods
        self.rod_insertion = 0.0
        self.rod_absorbed  = 0

        # Bookkeeping
        self.fissions      = 0
        self.cycle         = 1
        self.reload_timer  = 0
        self.neutrons      = []
        self.flashes       = []
        self.atoms         = build_hex_fuel()
        self._seed(count=INITIAL_NEUTRONS)

    def _seed(self, x=None, y=None, count=1):
        ox = x if x is not None else CX
        oy = y if y is not None else CY
        for _ in range(count):
            ang = random.uniform(0, 2 * math.pi)
            r   = VESSEL_IN * random.uniform(0.2, 0.6)
            nx  = ox + math.cos(ang) * r
            ny  = oy + math.sin(ang) * r
            if math.hypot(nx - CX, ny - CY) >= VESSEL_IN:
                nx, ny = CX, CY
            spd = NEUTRON_SPEED * random.uniform(0.9, 1.1)
            self.neutrons.append(
                Neutron(nx, ny, -math.cos(ang) * spd, -math.sin(ang) * spd))

    def _reload(self):
        self.cycle += 1
        for a in self.atoms:
            a.active = True
        for a in self.atoms:
            self.flashes.append(Flash(a.x, a.y))

    # ── Temperature ratios for visuals ────────────────────────────────────────

    @property
    def tr_cool(self):
        """Coolant temp ratio: 0 at inlet, 1 at full-power outlet."""
        return max(0.0, min(1.0, (self.coolant_temp - T_INLET) / 38.0))

    @property
    def tr_fuel(self):
        """Fuel centreline temp ratio: 0 at cold, 1 at UO₂ limit."""
        return max(0.0, min(1.0,
            (self.fuel_temp - T_INLET) / (T_FUEL_MAX - T_INLET)))

    # ── Physics update ─────────────────────────────────────────────────────────

    def update(self):
        # ── 1. Cross-section from fuel temperature (Doppler 1/v law) ──────────
        # As fuel temp rises, U-238 resonance capture widens (Doppler broadening)
        # and U-235 thermal fission cross-section falls → negative coefficient.
        T_fuel_K  = self.fuel_temp + 273.15
        self.sigma  = SIGMA_0 * math.sqrt(T_REF_K / T_fuel_K)
        # Hitbox radius is proportional to √σ (cross-section ∝ area)
        self.coll_r = BASE_COLL_R * math.sqrt(self.sigma / SIGMA_0)

        # ── 2. Move neutrons ───────────────────────────────────────────────────
        for n in self.neutrons:
            n.update()
        self.neutrons = [n for n in self.neutrons if n.alive]

        # ── 3. Collisions (fission) — uses live self.coll_r ───────────────────
        self._collide()

        # ── 4. Thermodynamic loop ──────────────────────────────────────────────
        # Heat conducts from fuel centreline to coolant
        q_transfer = FUEL_COOLANT_K * (self.fuel_temp - self.coolant_temp)
        self.fuel_temp    -= q_transfer
        self.coolant_temp += q_transfer * 0.80   # 80 % to coolant, 20 % radiated

        # Supplemental fuel radiation toward coolant
        self.fuel_temp += FUEL_RADIATION * (self.coolant_temp - self.fuel_temp)

        # External cooling loop drives coolant back toward inlet temperature
        self.coolant_temp -= COOLANT_DECAY * (self.coolant_temp - T_INLET)

        # Clamp to physical limits
        self.fuel_temp    = max(T_INLET, self.fuel_temp)
        self.coolant_temp = max(T_INLET, min(T_INLET + 38.0, self.coolant_temp))

        # ── 5. Neutron flux from particle dynamics ─────────────────────────────
        # Φ = n·v  (density × mean speed), then scaled to physical units
        core_n = [n for n in self.neutrons
                  if math.hypot(n.x - CX, n.y - CY) < CORE_R]
        if core_n:
            mean_spd_cms = (
                sum(math.hypot(n.vx, n.vy) for n in core_n) / len(core_n)
                / PX_PER_CM * FPS
            )
            density = len(core_n) / CORE_AREA_CM2
            self.neutron_flux = density * mean_spd_cms * FLUX_SCALE
        else:
            self.neutron_flux = 0.0

        # ── 6. k-effective — 60-frame generation window ────────────────────────
        self._gen_frame += 1
        if self._gen_frame >= K_CYCLE_FRAMES:
            curr = len(self.neutrons)
            k_raw = curr / max(self._gen_start_n, 1)
            self.k_eff = 0.85 * self.k_eff + 0.15 * k_raw  # EMA
            self._gen_start_n = curr
            self._gen_frame = 0

        # ── 7. Control rods ────────────────────────────────────────────────────
        # Insert proportionally when population overshoots target;
        # withdraw slowly when below target — mirrors SCRAM / power regulation.
        excess = len(self.neutrons) - CONTROL_TARGET_N
        if excess > 0:
            self.rod_insertion = min(1.0,
                self.rod_insertion + excess * CONTROL_SENSITIVITY)
        else:
            self.rod_insertion = max(0.0, self.rod_insertion - 0.005)

        absorb_p = self.rod_insertion * CONTROL_MAX_ABSORB
        survivors, absorbed = [], 0
        for n in self.neutrons:
            if excess > 0 and random.random() < absorb_p:
                absorbed += 1
            else:
                survivors.append(n)
        self.neutrons    = survivors
        self.rod_absorbed = absorbed

        # ── 8. Flashes and fuel reload ─────────────────────────────────────────
        for f in self.flashes:
            f.update()
        self.flashes = [f for f in self.flashes if f.alive]

        active = sum(1 for a in self.atoms if a.active)
        if active == 0:
            if self.reload_timer == 0:
                self.reload_timer = 90
            else:
                self.reload_timer -= 1
                if self.reload_timer == 1:
                    self._reload()

    def _collide(self):
        """
        Check each neutron against all active fuel atoms using the live
        self.coll_r (derived from the current cross-section σ).
        Coolant void coefficient gives a small additional escape probability
        when coolant temperature rises (less dense → worse moderator).
        """
        cr2     = self.coll_r ** 2
        # Void coefficient: 0–12 % extra escape as coolant heats up
        void_p  = 0.12 * self.tr_cool
        new     = []

        for n in self.neutrons:
            if not n.alive:
                continue
            for a in self.atoms:
                if not a.active:
                    continue
                dx = n.x - a.x
                dy = n.y - a.y
                if dx * dx + dy * dy > cr2:
                    continue

                # Void coefficient scatter (coolant density effect)
                if random.random() < void_p:
                    ang  = random.uniform(0, 2 * math.pi)
                    spd  = math.hypot(n.vx, n.vy)
                    n.vx = math.cos(ang) * spd
                    n.vy = math.sin(ang) * spd
                    break

                # Fission event
                a.active = False
                n.alive  = False
                self.fissions += 1
                self.flashes.append(Flash(a.x, a.y))

                # Each fission adds heat directly to fuel centreline
                self.fuel_temp += HEAT_PER_FISSION

                num_new = random.randint(2, 3)
                if len(self.neutrons) + len(new) < MAX_NEUTRONS:
                    for _ in range(num_new):
                        ang = random.uniform(0, 2 * math.pi)
                        spd = NEUTRON_SPEED * random.uniform(0.9, 1.3)
                        new.append(Neutron(a.x, a.y,
                                           math.cos(ang) * spd,
                                           math.sin(ang) * spd))
                break

        self.neutrons.extend(new)

    # ── Draw ───────────────────────────────────────────────────────────────────

    def draw(self):
        self.screen.fill(C_BG)
        draw_reactor(self.screen, self.tr_cool, self.tr_fuel)
        for a in self.atoms:   a.draw(self.screen)
        for f in self.flashes: f.draw(self.screen)
        for n in self.neutrons: n.draw(self.screen)
        self._hud()
        pygame.display.flip()

    def _hud(self):
        s      = self.screen
        active = sum(1 for a in self.atoms if a.active)

        # ── Right panel ────────────────────────────────────────────────────────
        PX, PY, PW = 780, 18, 352
        PH = 500
        pygame.draw.rect(s, C_PANEL_BG,   (PX, PY, PW, PH), border_radius=8)
        pygame.draw.rect(s, C_PANEL_EDGE, (PX, PY, PW, PH), 1, border_radius=8)

        BX = PX + 14
        RW = PW - 28   # inner width
        y  = PY + 10

        title = self.fmd.render("U-235  CHAIN REACTION", True, (95, 170, 255))
        s.blit(title, (PX + PW // 2 - title.get_width() // 2, y))
        y += 20
        pygame.draw.line(s, C_PANEL_EDGE, (PX + 12, y), (PX + PW - 12, y))
        y += 10

        # ── CORE TEMPERATURES ──────────────────────────────────────────────────
        s.blit(self.fmd.render("CORE TEMPERATURES", True, (95, 170, 255)), (BX, y))
        y += 16

        # Coolant temp bar
        ct_ratio = self.tr_cool
        pygame.draw.rect(s, C_BAR_BG,    (BX, y, RW, 12), border_radius=3)
        fw = int(RW * ct_ratio)
        if fw:
            pygame.draw.rect(s, lerp((18, 188, 78), (255, 28, 28), ct_ratio),
                             (BX, y, fw, 12), border_radius=3)
        pygame.draw.rect(s, C_BAR_BORDER, (BX, y, RW, 12), 1, border_radius=3)
        y += 14
        self._row(s, BX, PX, PW, y, "Coolant (hot-leg)",
                  f"{self.coolant_temp:.1f} °C", C_UI)
        y += 15

        # Fuel centreline bar
        ft_ratio = self.tr_fuel
        pygame.draw.rect(s, C_BAR_BG,    (BX, y, RW, 12), border_radius=3)
        fw = int(RW * ft_ratio)
        if fw:
            pygame.draw.rect(s, lerp((255, 160, 20), (255, 28, 28), ft_ratio),
                             (BX, y, fw, 12), border_radius=3)
        pygame.draw.rect(s, C_BAR_BORDER, (BX, y, RW, 12), 1, border_radius=3)
        y += 14
        self._row(s, BX, PX, PW, y, "Fuel centreline",
                  f"{self.fuel_temp:.1f} °C", C_UI)
        y += 16

        pygame.draw.line(s, C_PANEL_EDGE, (PX + 12, y), (PX + PW - 12, y))
        y += 10

        # ── NEUTRONICS ─────────────────────────────────────────────────────────
        s.blit(self.fmd.render("NEUTRONICS", True, (95, 170, 255)), (BX, y))
        y += 16

        # k-effective with colour coding
        if self.k_eff > 1.015:
            k_label, k_col = "supercritical", (255, 100, 40)
        elif self.k_eff > 0.985:
            k_label, k_col = "critical",      (50, 215, 85)
        else:
            k_label, k_col = "subcritical",   (140, 145, 175)

        self._row(s, BX, PX, PW, y, "k-effective  (60-frame avg)",
                  f"{self.k_eff:.3f}  {k_label}", k_col)
        y += 15
        self._row(s, BX, PX, PW, y, "Neutron flux  (Φ = n·v)",
                  fmt_flux(self.neutron_flux), C_UI)
        y += 15
        self._row(s, BX, PX, PW, y, "Active neutrons",
                  f"{len(self.neutrons)}", C_UI)
        y += 16

        pygame.draw.line(s, C_PANEL_EDGE, (PX + 12, y), (PX + PW - 12, y))
        y += 10

        # ── CROSS-SECTION & DOPPLER ────────────────────────────────────────────
        s.blit(self.fmd.render("CROSS-SECTION  (Doppler 1/v)", True, (95, 170, 255)),
               (BX, y))
        y += 16

        sigma_ratio = self.sigma / SIGMA_0      # 1.0 at cold, < 1.0 as fuel heats
        pygame.draw.rect(s, C_BAR_BG,    (BX, y, RW, 12), border_radius=3)
        fw = int(RW * sigma_ratio)
        if fw:
            pygame.draw.rect(s, lerp((255, 28, 28), (50, 200, 80), sigma_ratio),
                             (BX, y, fw, 12), border_radius=3)
        pygame.draw.rect(s, C_BAR_BORDER, (BX, y, RW, 12), 1, border_radius=3)
        y += 14
        self._row(s, BX, PX, PW, y, "σ fission (U-235)",
                  f"{self.sigma:.1f} barns", C_UI)
        y += 15
        self._row(s, BX, PX, PW, y, "Collision hitbox",
                  f"{self.coll_r:.2f} px  (↓ as fuel heats)", C_DIM)
        y += 15
        self._row(s, BX, PX, PW, y, "Void coeff. escape",
                  f"{self.tr_cool * 12:.1f}%", C_DIM)
        y += 16

        pygame.draw.line(s, C_PANEL_EDGE, (PX + 12, y), (PX + PW - 12, y))
        y += 10

        # ── CONTROL RODS ───────────────────────────────────────────────────────
        s.blit(self.fmd.render("CONTROL RODS", True, (95, 170, 255)), (BX, y))
        y += 16

        rod_col = lerp((50, 200, 80), (255, 40, 40), self.rod_insertion)
        pygame.draw.rect(s, C_BAR_BG,    (BX, y, RW, 12), border_radius=3)
        rfw = int(RW * self.rod_insertion)
        if rfw:
            pygame.draw.rect(s, rod_col, (BX, y, rfw, 12), border_radius=3)
        pygame.draw.rect(s, C_BAR_BORDER, (BX, y, RW, 12), 1, border_radius=3)
        y += 14
        self._row(s, BX, PX, PW, y, "Insertion depth",
                  f"{self.rod_insertion * 100:.0f}%", rod_col)
        y += 15
        self._row(s, BX, PX, PW, y, "Captured this frame",
                  f"{self.rod_absorbed} neutrons", C_DIM)
        y += 16

        pygame.draw.line(s, C_PANEL_EDGE, (PX + 12, y), (PX + PW - 12, y))
        y += 10

        # ── FUEL STATUS ────────────────────────────────────────────────────────
        self._row(s, BX, PX, PW, y, "Total fissions",
                  f"{self.fissions:,}", C_UI)
        y += 15
        self._row(s, BX, PX, PW, y, "Fuel rods remaining",
                  f"{active} / {len(self.atoms)}", C_UI)
        y += 15
        self._row(s, BX, PX, PW, y, "Fuel cycle",
                  f"{self.cycle}", C_UI)
        y += 18

        # Scaling footnote
        nc = (62, 68, 105)
        s.blit(self.fsm.render("* Flux & temps scaled to PWR operating", True, nc), (BX, y))
        s.blit(self.fsm.render("  ranges — see README for full mapping.", True, nc), (BX, y + 13))

        # ── Status badge ───────────────────────────────────────────────────────
        if active == 0 and self.reload_timer > 0:
            txt, sc = "RELOADING FUEL RODS", (85, 170, 255)
        elif self.fuel_temp > 1200:
            txt, sc = "⚠  HIGH FUEL TEMP",  (255, 38, 38)
        elif self.tr_cool > 0.6:
            txt, sc = "ELEVATED TEMP",       (255, 160, 28)
        else:
            txt, sc = "CHAIN REACTION",      (42, 210, 82)

        badge = self.fmd.render(txt, True, sc)
        s.blit(badge, (PX + PW // 2 - badge.get_width() // 2, PY + PH - 28))

        # ── Zone legend panel ──────────────────────────────────────────────────
        LX = PX
        LY = PY + PH + 14
        LH = 130
        if LY + LH < HEIGHT - 25:
            pygame.draw.rect(s, C_PANEL_BG,   (LX, LY, PW, LH), border_radius=8)
            pygame.draw.rect(s, C_PANEL_EDGE, (LX, LY, PW, LH), 1, border_radius=8)
            lt = self.fmd.render("REACTOR ZONES", True, (95, 170, 255))
            s.blit(lt, (LX + PW // 2 - lt.get_width() // 2, LY + 8))
            pygame.draw.line(s, C_PANEL_EDGE,
                             (LX + 12, LY + 27), (LX + PW - 12, LY + 27))
            zones = [
                (C_FUEL_OUT,  "U-235 Fuel Rods"),
                (lerp(C_CORE_COOL, C_CORE_HOT, self.tr_fuel), "Core / Reactor Centre"),
                (lerp(C_HOT_COOL,  C_HOT_HOT,  self.tr_cool), "Hot Coolant"),
                (C_MOD,       "Graphite Moderator"),
                (C_VESSEL_FILL, "Pressure Vessel"),
            ]
            zy = LY + 34
            for col, name in zones:
                pygame.draw.rect(s, col,   (LX + 14, zy, 18, 11), border_radius=2)
                pygame.draw.rect(s, C_DIM, (LX + 14, zy, 18, 11), 1, border_radius=2)
                s.blit(self.fsm.render(name, True, C_UI), (LX + 38, zy))
                zy += 18

        # ── Top title ──────────────────────────────────────────────────────────
        title = self.flg.render("Nuclear Fission Chain Reaction", True, (78, 162, 255))
        s.blit(title, (CX - title.get_width() // 2, 10))

        # ── Bottom hint ────────────────────────────────────────────────────────
        hint = self.fsm.render(
            "Click reactor = inject neutron   R = restart   P = pause   Q = quit",
            True, C_DIM)
        s.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 20))

        if self.paused:
            p = self.flg.render("—  PAUSED  —", True, (220, 220, 70))
            s.blit(p, (CX - p.get_width() // 2, CY - 12))

    def _row(self, s, bx, px, pw, y, label, val, col):
        """Draw a label-value row inside the right panel."""
        s.blit(self.fsm.render(label, True, C_DIM), (bx, y))
        v = self.fsm.render(val, True, col)
        s.blit(v, (px + pw - 14 - v.get_width(), y))

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        while self.running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False
                elif ev.type == pygame.KEYDOWN:
                    k = ev.key
                    if k in (pygame.K_q, pygame.K_ESCAPE):
                        self.running = False
                    elif k == pygame.K_r:
                        self._reset()
                    elif k == pygame.K_p:
                        self.paused = not self.paused
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    mx, my = pygame.mouse.get_pos()
                    if math.hypot(mx - CX, my - CY) < VESSEL_IN:
                        self.neutrons.append(Neutron(mx, my))

            if not self.paused:
                self.update()
            self.draw()
            self.clock.tick(FPS)

        pygame.quit()
        sys.exit(0)


if __name__ == "__main__":
    Simulation().run()