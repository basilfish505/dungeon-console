# Create a 50x50 square box of asterisks
for i in range(50):
    if i == 0 or i == 49:  # First and last rows
        print('*' * 50)
    else:  # Middle rows
        print('*' + ' ' * 48 + '*')
