import argparse
import sys

from llm import provider_config


def main():
    parser = argparse.ArgumentParser(description="AI Software Engineer Agent")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="choose or change the AI provider (free local, free hosted, or your own key)",
    )
    parser.add_argument(
        "--trust-repo-config",
        action="store_true",
        help="let the target repo's .ai-agent.yml choose the install and test commands "
             "(it can run any command on this machine; only use it for repos you trust)",
    )
    args = parser.parse_args()

    try:
        if args.setup:
            provider_config.run_setup()
            return
        cfg = provider_config.ensure_configured()
        print(f"[AI-ENGINEER] {provider_config.describe(cfg)}")
    except provider_config.ConfigError as e:
        print(e)
        sys.exit(1)

    # Imported late so `--setup` works before GITHUB_TOKEN is configured
    from agent.code_agent import CodeAgent

    owner = input("Repo Owner: ")
    repo = input("Repo Name: ")
    issue_number = int(input("Issue Number: "))

    agent = CodeAgent(trust_repo_config=args.trust_repo_config)
    agent.run(owner, repo, issue_number)


if __name__ == "__main__":
    main()
