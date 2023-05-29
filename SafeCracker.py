import Safe as Safe
import asyncio
import random

#********************************************************************************************
# Welcome to the Safe Cracker challenge!
#
# GOAL: 
# You are competing against 5 other algorithms to crack a 4 digit (0-9) safe.
# The safe will run over 10 iterations (with changing combinations) and get the average cracking time of all algorithms.
# For each algorithm you're faster than, you will be rewarded with extra points.
# If you beat any of the secret algorithms, you will also be rewarded with the passcode to the real safe!
# The safe contains the main ATR flag.
#
# RULES:
# 1. You may modify the main function to pre-generate arrays and optionally pass it into crack_the_safe. 
# 2. You must implement your safe cracking algorithm in the crack_the_safe function.
# 3. Use the check_combination method to check if a combination is correct. It expects an integer and returns true or false.
# 4. The timer for your algorithm begins when the start_cracking method is called and ends when the combination is cracked (preprocessing in main is not timed).
# 5. Ask for help from activity leaders or lecturers and tech experts if you are stuck!
#
# CLUE: 
# The safe may follow a pattern to its combinations.
#
# CODE SNIPPET:
# cracked = await safe.check_combination(i)
# count+=1 
# if cracked:
#     print(f"Cracked the safe using YOUR TEAM'S algorithm with {count} attempts" + f" The combination is {i} and it took {safe.crack_time:.8f} seconds")
#     break
#********************************************************************************************

# Implement your own algorithm here!
async def crack_the_safe(safe: Safe.Safe, array):
    # Random algorithm example
    count = 0
    while(True):
        count += 1
        guess = random.randint(0,9999)
        # check a random int from 0 to 9999
        if await safe.check_combination(guess):
            print(f"Cracked the safe using YOUR TEAM'S algorithm with {count} attempts" + f" The combination is {guess} and it took {safe.crack_time:.8f} seconds")
            break

# Main function
async def main():
    safe = Safe.Safe()

    # Pre-generate arrays here if you wish
    array = []

    await safe.start_cracking(crack_the_safe, array) # type: ignore

if __name__ == '__main__':
    asyncio.run(main())
