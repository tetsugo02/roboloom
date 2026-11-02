"""Minimal Python entry point; see README for the full InProcessSession API."""

from roboloom import InProcessSession


def main():
    with InProcessSession.from_yaml("examples/mock/config.yaml") as session:
        session.start_episode("mock handover")
        session.run(1.0)
        session.stop_episode()
        print(f"saved {session.save_episode()} frames")


if __name__ == "__main__":
    main()
