"""URDF forward kinematics in numpy: joint axes and link frames only, no meshes or masses."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np


def rpy_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr, cp, sp, cy, sy = (
        np.cos(roll),
        np.sin(roll),
        np.cos(pitch),
        np.sin(pitch),
        np.cos(yaw),
        np.sin(yaw),
    )
    return np.array(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ]
    )


def axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    x, y, z = axis
    c, s = np.cos(angle), np.sin(angle)
    k = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + s * k + (1 - c) * (k @ k)


@dataclass
class Joint:
    name: str
    kind: str
    parent: str
    child: str
    xyz: np.ndarray
    rotation: np.ndarray
    axis: np.ndarray


@dataclass
class Frame:
    origin: np.ndarray
    rotation: np.ndarray


class UrdfTree:
    def __init__(self, joints: list[Joint]):
        self.joints = {j.name: j for j in joints}
        self.by_child = {j.child: j for j in joints}
        children = {j.child for j in joints}
        roots = {j.parent for j in joints} - children
        if len(roots) != 1:
            raise ValueError(f"URDF must have one root link, found {sorted(roots)}")
        (self.root,) = roots
        self.order: list[Joint] = []  # parents before children
        frontier = [self.root]
        by_parent: dict[str, list[Joint]] = {}
        for j in joints:
            by_parent.setdefault(j.parent, []).append(j)
        while frontier:
            link = frontier.pop()
            for j in by_parent.get(link, []):
                self.order.append(j)
                frontier.append(j.child)

    @classmethod
    def parse(cls, text: str) -> UrdfTree:
        joints = []
        for el in ET.fromstring(text).findall("joint"):
            origin = el.find("origin")
            xyz = np.array(
                [
                    float(v)
                    for v in (
                        origin.get("xyz", "0 0 0") if origin is not None else "0 0 0"
                    ).split()
                ]
            )
            rpy = [
                float(v)
                for v in (
                    origin.get("rpy", "0 0 0") if origin is not None else "0 0 0"
                ).split()
            ]
            axis_el = el.find("axis")
            axis = np.array(
                [
                    float(v)
                    for v in (
                        axis_el.get("xyz", "1 0 0") if axis_el is not None else "1 0 0"
                    ).split()
                ]
            )
            parent, child = el.find("parent"), el.find("child")
            if parent is None or child is None:
                raise ValueError(f"joint {el.get('name')} lacks parent or child")
            joints.append(
                Joint(
                    el.get("name", ""),
                    el.get("type", "fixed"),
                    parent.get("link", ""),
                    child.get("link", ""),
                    xyz,
                    rpy_matrix(*rpy),
                    axis / np.linalg.norm(axis),
                )
            )
        return cls(joints)

    def movable(self) -> list[str]:
        return [j.name for j in self.order if j.kind in ("revolute", "continuous")]

    def frames(
        self, angles: Mapping[str, float]
    ) -> tuple[dict[str, Frame], dict[str, Frame]]:
        """World frames of every link, and of every movable joint (origin, axis in world = rotation @ axis)."""
        links = {self.root: Frame(np.zeros(3), np.eye(3))}
        joints = {}
        for j in self.order:
            parent = links[j.parent]
            origin = parent.origin + parent.rotation @ j.xyz
            rotation = parent.rotation @ j.rotation
            if j.kind in ("revolute", "continuous"):
                joints[j.name] = Frame(origin, rotation)
                rotation = rotation @ axis_angle(j.axis, angles.get(j.name, 0.0))
            elif j.kind != "fixed":
                raise ValueError(f"unsupported joint type {j.kind} ({j.name})")
            links[j.child] = Frame(origin, rotation)
        return links, joints

    def subtree_joints(self, joint: str) -> list[str]:
        """Movable joints at or below `joint`, parents first."""
        below = {self.joints[joint].child}
        out = [joint]
        for j in self.order:
            if j.parent in below:
                below.add(j.child)
                if j.kind in ("revolute", "continuous"):
                    out.append(j.name)
        return out

    def restricted(self, joint_names: list[str]) -> UrdfTree:
        """The joints on the paths from the root to `joint_names` (and those joints): enough for their frames."""
        keep = set()
        for name in joint_names:
            joint: Joint | None = self.joints[name]
            while joint is not None and joint.name not in keep:
                keep.add(joint.name)
                joint = self.by_child.get(joint.parent)
        return UrdfTree([j for j in self.order if j.name in keep])
