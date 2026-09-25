"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. See routes.py for the full function list.
"""
import json
import os

from similarweb import rankings, websites

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a domain (any link on the site works too)
    save("website_amazon.com.json", websites.details("amazon.com"))

    # up to 10 domains side by side
    save("compare_code_hosts.json", websites.compare(["github.com", "gitlab.com", "bitbucket.org"]))

    # the 50 most visited AI websites worldwide
    save("top_websites_ai.json", rankings.top_websites(category={"category": "ai-chatbots-and-tools", "subcategory": None}))
