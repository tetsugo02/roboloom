"""Minimal Python entry point; see README for the full InProcessSession API."""

from roboloom import InProcessSession


def main():
    with InProcessSession.from_yaml("examples/mock/config.yaml") as experiment:
        experiment.start_episode("mock handover")
        experiment.run(1.0)
        experiment.stop_episode()
        print(f"saved {experiment.save_episode()} frames")


if __name__ == "__main__":
    main()
