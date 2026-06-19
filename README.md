# Nuclear Fission Chain Reaction Simulation

A 2D simulation of a U-235 fission chain reaction, built in Python with pygame. The visual layout mirrors real PWR reactor cross-section diagrams, and every statistic in the UI panel is driven by live particle dynamics, not hardcoded formulas.

---

## Features

- **Hex-packed fuel rod array**: Fuel rods arranged in a circular core, matching real reactor cross-section geometry
- **Layered reactor zones**: Fuel core, hot coolant ring, graphite moderator with concentric texture, thick pressure vessel wall
- **Live particle physics**: Neutrons move, collide, and spawn daughter neutrons; all stats update from the actual particle state each frame
- **Automatic control rods**: Control rods insert proportionally when neutron population overshoots the target, mirroring real SCRAM logic
- **Continuous reaction**: Neutrons reflect off the inner vessel wall. Fuel reloads automatically when depleted

---

## Installation

```bash
pip install pygame
python fission_sim.py
```

Requires Python 3.9+.

---

## Controls

| Key / Action | Effect |
|---|---|
| Click inside reactor | Inject a neutron at that position |
| R | Restart simulation |
| P | Pause / unpause |
| Q or Esc | Quit |

---

## How the Physics Works

### Fission chain reaction

When a neutron collides with an active U-235 fuel rod, that rod is consumed, a flash is emitted representing energy release, and 2 – 3 daughter neutrons are spawned in random directions. Those neutrons go on to trigger further fissions creating a chain reaction. Each fission event also adds heat directly to the fuel centreline temperature.

### Negative temperature coefficient

This is the key passive safety mechanism in real light-water reactors. As temperature rises, two effects suppress the reaction:

1. **Doppler broadening**: The fission cross-section σ falls with fuel temperature via the 1/v law: σ(T) = σ₀ × √(T_ref / T_fuel). This directly shrinks the collision hitbox on every fuel rod each frame, so neutrons are physically less likely to cause fission when the core is hot.
2. **Void coefficient**: Hotter coolant is less dense, making it a worse neutron moderator. Modelled as a small additional scatter probability (0 – 12%) that rises with coolant temperature.

Together these mean a runaway reaction heats the core, which suppresses further fission, which lets the core cool, creating a self stabilising loop requiring no external intervention.

### Thermodynamic loop

Two temperatures are tracked separately and coupled by heat transfer:

- **Fuel centreline temperature**: Rises with each fission event, conducts heat to coolant
- **Coolant temperature**: Receives heat from fuel, then falls back toward the inlet temperature (287 °C) via the external cooling loop

This means the hot coolant ring and core background colours in the visualisation reflect genuinely different temperatures that evolve independently.

### Control rods

Automatic control rods insert proportionally when the neutron population exceeds the target (Approx. 80 neutrons). Each inserted rod absorbs excess neutrons stochastically each frame. Rods withdraw slowly when population is below target. This mirrors the power regulation and SCRAM logic in real pressurised water reactors (PWRs).

---

## UI Panel: Real Unit Mappings

All statistics are computed from particle dynamics and mapped to realistic PWR operating ranges. The physics ratios are preserved. only the absolute scale is compressed to fit a 2D particle simulation.

| Stat | How it's computed | Real-world range |
|---|---|---|
| **Coolant temperature** | Linear map from simulation thermal state | 287 – 325 °C (PWR hot leg range) |
| **Fuel centreline temperature** | Separate variable, heated by fissions, cooled by conduction | 290 – 1400 °C (UO₂ melting limit) |
| **Neutron flux Φ** | Φ = n x v (core particle density × mean neutron speed, scaled to physical units) | 10¹² – 10¹³ n/cm²/s (startup to full power) |
| **Fission cross-section σ** | σ = 585 × √(293 K / T_fuel_K) barns (doppler 1/v law applied live each frame) | 585 b (cold) to 245 b (hot fuel) |
| **k-effective** | Neutron population ratio measured across 60 frame generation windows, smoothed with an EMA | >1 supercritical =1 critical <1 subcritical |
| **Control rod insertion** | Rod depth proportional to population overshoot above target | 0 % withdrawn to 100 % fully inserted |

### Flux calibration

The flux scale factor is computed at startup so that the target steady state neutron population maps to 5×10¹² n/cm²/s, the order of magnitude for a PWR operating at startup power. At peak neutron count this reaches about 3×10¹³ n/cm²/s, consistent with full power thermal flux in a commercial reactor.

---

## Accurate Reactor Dynamics Modeled

- U-235 releases 2 – 3 neutrons per fission (real world average: 2.43)
- Negative temperature coefficient: the reaction passively self-limits as temperature rises
- Separate fuel and coolant temperatures coupled by heat transfer
- Cross-section physically shrinks the collision hitboxes as fuel heats up
- k-effective measured from actual neutron generation ratios
- Control rods absorb neutrons to regulate population, matching real reactor control logic
- Fuel depletion and automatic reload (similar to refuelling outages)

## What Is Simplified

- The simulation is 2D (real reactors are 3D cylinders)
- Neutrons are monoenergetic (no thermal/fast spectrum distinction)
- No neutron moderation (slowing from fast to thermal energies)
- No delayed neutrons (Approximately 0.65% of real fission neutrons are released seconds later, which is what makes reactors controllable in practice)
- No xenon poisoning or other fission product buildup
- The 1/v cross-section law used here is an approximation. Real Doppler broadening involves resonance integrals over the neutron energy spectrum

---

## References & Technical Literature
- World Nuclear Association - Physics of Uranium and Nuclear Energy
  https://world-nuclear.org/information-library/nuclear-fuel-cycle/introduction/physics-of-nuclear-energy
- U.S. NRC Technical Training Center - Reactor Physics & Thermal Hydraulics Manual
  https://www.nrc.gov/docs/ml1122/ml11223a207.pdf
- U.S. Nuclear Regulatory Commission (NRC) - Pressurized Water Reactors
  https://www.nrc.gov/reactors/power/pwrs
- World Nuclear Association - Nuclear Power Reactors 
  https://world-nuclear.org/information-library/nuclear-power-reactors/overview/nuclear-power-reactors
- U.S. NRC - Pressurized Water Reactor Systems
  https://www.nrc.gov/reading-rm/basic-ref/students/for-educators/04.pdf
- Nuclear Power.com - Doppler Broadening & Resonance Absorption
  https://www.nuclear-power.com/glossary/doppler-broadening/
- IAEA INIS Repository - Cross Sections and Neutron Yields for U-235
  https://inis.iaea.org/records/gg1r3-dfe40/files/38114945.pdf?download=1
- Idaho National Laboratory (INL) Digital Library - Scaling for Nuclear Power System
  https://inldigitallibrary.inl.gov/content/uploads/50/2026/04/Sort_65237.pdf
- IAEA Nucleus - Neutron Flux Measurement via Gold Foil Activation
https://nucleus.iaea.org/sites/connect/RRIHpublic/CompendiumDB/Shared%20Documents/Switzerland/Protocols%20in%20PDF/Protocol%20Gold%20Foils.pdf
