"""How well an arm's inverse kinematics is conditioned (needs the `ik` extra).

    uv run python scripts/ik_conditioning.py rakuda2            # the template, both arms
    uv run python scripts/ik_conditioning.py .roboloom/piper-mock/config.yaml

For every follower (or part of one) that has a kinematic model it samples joint poses
inside the follower's limits and prints the smallest singular value of the tool
Jacobian (m/rad): for the full pose (position and orientation, what `pose_ik` solves),
for the position alone and for the orientation alone. A small value means there is a
direction the tool can hardly move in from that pose; `pose_ik` then reports
`unreachable`. It also prints each joint's axis and origin at the URDF's zero pose, to
compare with the robot, and the weakest direction at the zero pose.

The numbers quoted in docs/*/contribution/rakuda2-pika.md come from this script
(seed 1, 3000 samples).
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from roboloom.config import load_config, parse_config, read_config
from roboloom.kinematics.ik import ArmModel


def chains(cfg):
    """(name, spec, limits) of every described chain: whole followers and their parts."""
    for follower in cfg.followers.values():
        for owner in (follower, *(follower.part(p) for p in follower.parts())):
            spec = owner.kinematics()
            if spec is not None:
                yield owner.name, spec, owner.limits


def jacobian(model: ArmModel, q):
    pin = model.pin
    return pin.computeFrameJacobian(
        model.model,
        model.data,
        model._q(q),
        model.tool,
        pin.ReferenceFrame.LOCAL_WORLD_ALIGNED,
    )


def report(name: str, spec, limits, samples: int, seed: int, span: float) -> None:
    model = ArmModel(spec)
    low, high = spec.model_limits(
        [limit["min"] for limit in limits], [limit["max"] for limit in limits]
    )
    # the configured range can be the whole encoder turn; keep to +-span rad around zero
    low, high = np.maximum(low, -span), np.minimum(high, span)
    rng = np.random.default_rng(seed)
    full, position, rotation = [], [], []
    for _ in range(samples):
        j = jacobian(model, rng.uniform(low, high))
        full.append(np.linalg.svd(j, compute_uv=False)[-1])
        position.append(np.linalg.svd(j[:3], compute_uv=False)[-1])
        rotation.append(np.linalg.svd(j[3:], compute_uv=False)[-1])
    print(f"\n{name}  ({samples} poses within +-{span:g} rad of the URDF zero pose)")
    print("  smallest singular value of the tool Jacobian, 5% / median / 95%")
    for label, values in (
        ("position + orientation (m/rad)", full),
        ("position only          (m/rad)", position),
        ("orientation only     (rad/rad)", rotation),
    ):
        p = np.percentile(values, [5, 50, 95])
        print(f"    {label}: {p[0]:.4f} / {p[1]:.4f} / {p[2]:.4f}")

    pin = model.pin
    zero = model._q([0.0] * len(spec.joints))
    pin.forwardKinematics(model.model, model.data, zero)
    pin.updateFramePlacements(model.model, model.data)
    pin.computeJointJacobians(model.model, model.data, zero)
    base = model.data.oMf[model.base]
    print("  joints at the URDF zero pose, in the base frame (origin m, axis)")
    for follower_name, joint in zip(spec.names, spec.joints, strict=True):
        jid = model.model.getJointId(joint)
        placement = base.actInv(model.data.oMi[jid])
        column = pin.getJointJacobian(
            model.model, model.data, jid, pin.ReferenceFrame.LOCAL
        )[:, model.model.joints[jid].idx_v]
        axis = placement.rotation @ column[3:]
        print(
            f"    {follower_name:18s} {joint:28s} "
            f"{np.round(placement.translation, 3)} {np.round(axis, 2)}"
        )
    tip = base.actInv(model.data.oMf[model.tool]).translation
    print(
        f"    tool {np.round(tip, 3)}  (reach from the first joint: "
        f"{np.linalg.norm(tip - base.actInv(model.data.oMi[model.model.getJointId(spec.joints[0])]).translation):.3f} m)"
    )
    u, s, _ = np.linalg.svd(jacobian(model, [0.0] * len(spec.joints)))
    print(f"  at the zero pose: singular values {np.round(s, 4)}")
    print(f"    weakest direction [vx vy vz wx wy wz] {np.round(u[:, -1], 2)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "config", help="a configuration YAML, or `rakuda2` for the shipped template"
    )
    parser.add_argument("--samples", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--span", type=float, default=1.5, help="rad around zero")
    args = parser.parse_args()
    if args.config == "rakuda2":
        from importlib import resources

        path = resources.files("roboloom").joinpath(
            "robots/rakuda2/template/config.yaml"
        )
        tree = read_config(str(path), mock=True)
        tree["followers"]["follower"]["port"] = "/dev/null"
        for node in tree["inputs"].values():
            node["port"] = "/dev/null0"
        for sensor in tree["sensors"].values():
            sensor["serial"] = "0"
        cfg = parse_config(tree)
    else:
        cfg = load_config(args.config)
    found = False
    for name, spec, limits in chains(cfg):
        found = True
        report(name, spec, limits, args.samples, args.seed, args.span)
    if not found:
        sys.exit("no follower of this configuration has a kinematic model")


if __name__ == "__main__":
    main()
