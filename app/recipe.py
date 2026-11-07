"""The chocolate cake recipe behind the "Do you want a chocolate cake recipe?" suggestion.

Fixed text, saved as a conversation by POST /api/conversations/recipe. No model call and
no run row, so it costs nothing; the user message still counts toward the hourly limit.
"""

TITLE = "Chocolate cake recipe"
QUESTION = "Do you want a chocolate cake recipe?"
ANSWER = """**Simple chocolate cake** (one 24 cm round pan, about 10 slices)

**Ingredients**
- 2 cups (250 g) flour
- 2 cups (400 g) sugar
- ¾ cup (75 g) cocoa powder
- 2 tsp baking powder
- 1 tsp baking soda
- ½ tsp salt
- 2 eggs
- 1 cup (240 ml) milk
- ½ cup (120 ml) vegetable oil
- 2 tsp vanilla extract
- 1 cup (240 ml) hot water or hot coffee

**Steps**
1. Heat the oven to 180 °C. Grease the pan and line the bottom with baking paper.
2. In a large bowl, mix the flour, sugar, cocoa, baking powder, baking soda and salt.
3. Add the eggs, milk, oil and vanilla. Whisk for 2 minutes until smooth.
4. Stir in the hot water. The batter will be thin; that is right.
5. Pour into the pan and bake 35–40 minutes, until a toothpick in the centre comes out clean.
6. Cool 10 minutes in the pan, then turn out onto a rack and cool completely.

**Quick chocolate glaze (optional):** melt 100 g dark chocolate with ½ cup (120 ml) cream, stir until smooth, and pour over the cooled cake."""
