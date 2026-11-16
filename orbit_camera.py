"""Shared Y-up orbit camera convention for mesh and 3DGS renderers."""
import math
import numpy as np


def orbit_basis(center, distance, yaw=0.0, pitch=0.0, roll=0.0):
    """Return eye and camera-to-world right/up/back vectors.

    Yaw 0 is +Z; positive yaw moves toward +X. Positive pitch looks down.
    Positive roll tilts the rendered object clockwise in the image.
    """
    if not np.isfinite([distance, yaw, pitch, roll]).all() or distance <= 0:
        raise ValueError("Camera parameters must be finite and distance positive")
    if not -90 <= pitch <= 90:
        raise ValueError("--pitch must be within [-90, 90] degrees")
    a, b, r = map(math.radians, (yaw, pitch, roll))
    offset = np.array([math.sin(a)*math.cos(b), math.sin(b), math.cos(a)*math.cos(b)])
    eye = np.asarray(center, dtype=np.float64) + distance * offset
    # Analytic tangent basis avoids singularities at pitch +/-90.
    right = np.array([math.cos(a), 0.0, -math.sin(a)])
    up = np.array([-math.sin(a)*math.sin(b), math.cos(b), -math.cos(a)*math.sin(b)])
    # Positive roll makes the image horizon tilt clockwise.
    right, up = math.cos(r)*right + math.sin(r)*up, -math.sin(r)*right + math.cos(r)*up
    back = offset
    return eye, right, up, back


def orbit_view(center, distance, yaw=0.0, pitch=0.0, roll=0.0):
    eye, right, up, back = orbit_basis(center, distance, yaw, pitch, roll)
    view = np.eye(4)
    view[:3, :3] = np.stack((right, up, back))
    view[:3, 3] = -view[:3, :3] @ eye
    return view
