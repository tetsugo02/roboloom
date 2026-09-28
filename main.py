"""Minimal Python entry point; see README for the full Experiment API."""

from roboloom import Experiment


def main():
    with Experiment.from_yaml("examples/mock/experiment.yaml") as experiment:
        experiment.start_episode("mock handover")
        experiment.run(1.0)
        experiment.stop_episode()
        print(f"saved {experiment.save_episode()} frames")


if __name__ == "__main__":
    main()
