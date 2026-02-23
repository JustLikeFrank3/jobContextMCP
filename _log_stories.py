from tools.context import log_personal_story
from tools.star import get_star_story_context

r1 = log_personal_story(
    title="The name Vladmir - how a great-grandmother spelled it",
    story="My middle name is Vladmir - no I between the D and M. The standard spelling is Vladimir, but that is not how my great-grandmother wrote it. She had read the name in a book as a child and liked it. When she named my grandfather, she wrote it Vladmir. Whether she misspelled it or made it her own, I do not know - but that is the name she put on paper, and it carried. My grandfather was Frank Vladmir MacBride Sr. I am Frank Vladmir MacBride III. The name above my desk in that 1933 photograph is spelled the same way mine is.",
    tags=["family", "identity", "grandfather", "namesake", "motivation"],
    people=["Frank Vladmir MacBride Sr.", "Great-grandmother MacBride"]
)
print(r1)

r2 = log_personal_story(
    title="The Vladmir Bug - cost of assumptions vs. one clarifying question",
    story="When generating resume PDFs, I saw the name Vladmir throughout the files. I assumed it was a typo for Vladimir and fixed it everywhere - export.py in three places, 18+ txt files, re-exported PDFs twice. Then Frank told me: the correct family spelling IS Vladmir. His great-grandmother spelled it that way when she named his grandfather, and it has carried through three generations. I had to revert every change: grep the workspace, re-run sed, restore the code, export a third time. One question - how do you spell your middle name - eliminates the entire second and third pass. The cost of the unchecked assumption was higher than the cost of the question.",
    tags=["assumptions", "clarifying-questions", "process", "lessons-learned", "requirements-gathering"],
    people=["Frank Vladmir MacBride Sr."]
)
print(r2)

print()
print(get_star_story_context("assumptions"))
