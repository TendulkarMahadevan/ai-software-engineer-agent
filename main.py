from agent.code_agent import CodeAgent

if __name__ == "__main__":
    owner = input("Repo Owner: ")
    repo = input("Repo Name: ")
    issue_number = int(input("Issue Number: "))
    keyword = input("Search Keyword: ")

    agent = CodeAgent()
    agent.run(owner, repo, issue_number, keyword)

