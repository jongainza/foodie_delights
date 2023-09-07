from flask import (
    Flask,
    render_template,
    redirect,
    session,
    flash,
    g,
    request,
    url_for,
    abort,
)
from flask_debugtoolbar import DebugToolbarExtension
from models import (
    connect_db,
    db,
    User,
    Recipe,
    Ingredient,
    Instruction,
    SavedRecipe,
    Comment,
)

from forms import (
    RegistrationForm,
    LoginForm,
    CommentForm,
    RecipeForm,
    IngredientsForm,
    InstructionsForm,
)
from sqlalchemy.exc import IntegrityError, NoResultFound
import requests, json
from sqlalchemy import or_, func
from datetime import datetime
import random


spoonacular_api_key = "f89f72907ab54854aa13dcf946a10079"
# "35a15401df8045c189874b3ddcacadbb"
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql:///foodie_db"
app.app_context().push()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ECHO"] = True
app.config["SECRET_KEY"] = "abc123"
app.config["DEBUG_TB_INTERCEPT_REDIRECTS"] = False

connect_db(app)
db.drop_all()
db.create_all()

toolbar = DebugToolbarExtension(app)


res = requests.get(
    "https://api.spoonacular.com/recipes/642927/analyzedInstructions",
    params={
        # "query": "fish",
        # "includeIngredients": "cheese",
        # "number": 2,
        "apiKey": "35a15401df8045c189874b3ddcacadbb",
    },
)
# User Authentication


@app.route("/register", methods=["GET", "POST"])
def register():
    # Handle user registration form submission and data validation

    form = RegistrationForm()

    if form.validate_on_submit():
        try:
            new_user = User.register(
                username=form.username.data,
                password=form.password.data,
                email=form.email.data,
                image_url=form.image_url.data or User.image_url.default.arg,
            )
            db.session.add(new_user)
            db.session.commit()
            session["user_id"] = new_user.id
            session["user_name"] = new_user.username
            flash("Welcome! Successfully Created Your Account!")
            return redirect(f"/profile/{new_user.id}")

        except IntegrityError:
            db.session.rollback()
            flash("Username already taken", "danger")
            return render_template("/users/register.html", form=form)

    else:
        return render_template("users/register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    # Handle user login form submission and authentication

    form = LoginForm()

    if form.validate_on_submit():
        user = User.authenticate(form.username.data, form.password.data)

        if user:
            flash(f"Welcome Back!, {user.username}!", "success")
            session["user_id"] = user.id
            session["user_name"] = user.username
            return redirect(f"/profile/{user.id}")
        else:
            form.username.errors = ["Invalid username/password"]

    return render_template("users/login.html", form=form)


@app.route("/logout")
def logout():
    # Logout the current user and redirect to the homepage
    # Example: logout_user() from Flask-Login
    """Handle logout of user."""
    session.pop("user_id", "user_name")
    flash("Goodbye!")
    return redirect("/")


@app.route("/")
def home():
    if "user_id" in session:
        user_id = session["user_id"]

        # check if user exists in database
        user = User.query.get(user_id)

        if user is not None:
            return redirect(f"/profile/{session['user_id']}")

        # if the user is not in the database clear the session
        session.pop("user_id")

    return render_template("index.html")


@app.route("/profile/<int:user_id>")
def show_profile(user_id):  # Retrieve user details from the database
    if "user_id" not in session:
        flash("Please login first!")
        return redirect("/login")

    user = User.query.get_or_404(user_id)

    # Retrieve saved recipes from the database
    saved_recipes = user.saved_recipes

    # Retrieve user-generated recipes from the database
    user_generated_recipes = Recipe.query.filter_by(user_id=user_id).all()

    # Pass user data and other data to the template
    return render_template(
        "users/user_profile.html",
        user=user,
        saved_recipes=saved_recipes,
        user_generated_recipes=user_generated_recipes,
    )


import random


@app.route("/recipe", methods=["GET"])
def search_recipes():
    ingredient = request.args.get("ingredient")

    if ingredient:
        # Fetch random recipes containing ingredient from the database
        db_recipes = (
            Recipe.query.join(Ingredient)
            .filter(Ingredient.name == ingredient)
            .order_by(func.random())
            .limit(5)
            .all()
        )

        # Extract existing titles in the database
        existing_db_titles = [recipe.title for recipe in db_recipes]

        # Calculate the number of missing database recipes
        num_missing_db_recipes = 10 - len(db_recipes)

        if num_missing_db_recipes > 0:
            # Fetch additional random API recipes, filtering out duplicates
            additional_api_recipes = fetch_additional_api_recipes(
                ingredient, num_missing_db_recipes, existing_db_titles
            )

            # Shuffle the API recipes randomly
            random.shuffle(additional_api_recipes)

        return render_template(
            "recipes.html",
            api_recipes=additional_api_recipes,
            db_recipes=db_recipes,
            ingredient=ingredient,
        )

    return render_template("recipes.html", api_recipes=None, db_recipes=None)


def fetch_additional_api_recipes(ingredient, num_missing, existing_titles):
    additional_api_recipes = []

    while num_missing > 0:
        # Fetch a batch of random API recipes
        batch_size = min(num_missing, 10)  # Fetch up to 10 at a time
        api_recipes = requests.get(
            f"https://api.spoonacular.com/recipes/findByIngredients",
            params={
                "ingredients": ingredient,
                "number": batch_size,
                "apiKey": spoonacular_api_key,
                "random": True,
            },
        ).json()

        # Filter out API recipes with titles already in the database
        api_recipes = [
            recipe for recipe in api_recipes if recipe["title"] not in existing_titles
        ]

        # Add the filtered API recipes to the result
        additional_api_recipes.extend(api_recipes)

        # Update the number of missing recipes
        num_missing -= len(api_recipes)

    return additional_api_recipes


@app.route("/recipe/api/<int:recipe_id>")
def api_recipe_detail(recipe_id):
    # Fetch the recipe from the API
    url = f"https://api.spoonacular.com/recipes/{recipe_id}/information"
    params = {"apiKey": spoonacular_api_key}

    response = requests.get(url, params=params)
    api_recipe_data = response.json()

    # Create a dictionary with the necessary recipe details(this way I don't store recipes in my db, only if a user saves them)
    recipe = {
        "id": recipe_id,
        "title": api_recipe_data["title"],
        "image": api_recipe_data["image"],
        "extendedIngredients": api_recipe_data.get("extendedIngredients", []),
        "analyzedInstructions": api_recipe_data.get("analyzedInstructions", []),
    }

    return render_template(
        "recipe_detail.html",
        recipe=recipe,
        recipe_id=recipe_id,
    )


@app.route("/recipe/db/<int:recipe_id>")
def db_recipe_detail(recipe_id):
    # Fetch the recipe from the database
    recipe = Recipe.query.get(recipe_id)

    user_id = session.get("user_id")
    saved_recipe = SavedRecipe.query.filter_by(
        user_id=user_id, recipe_id=recipe_id
    ).first()
    comments = Comment.query.filter_by(recipe_id=recipe_id).all()

    form = CommentForm()
    if saved_recipe:
        return render_template(
            "recipe_detail.html",
            recipe=recipe,
            saved_recipe=saved_recipe,
            comments=comments,
            form=form,
            user=session["user_id"],
        )
    else:
        return render_template(
            "recipe_detail.html",
            recipe=recipe,
            comments=comments,
            form=form,
        )


# User Interaction
@app.route("/recipe/<int:recipe_id>/save", methods=["GET", "POST"])
def save_recipe(recipe_id):
    # Fetch recipe details from the API
    url = f"https://api.spoonacular.com/recipes/{recipe_id}/information"
    params = {"apiKey": spoonacular_api_key}

    response = requests.get(url, params=params)
    recipe_data = response.json()

    # Extract relevant recipe details
    recipe_title = recipe_data["title"]
    recipe_image = recipe_data["image"]
    ingredient_names = [
        ingredient["name"] for ingredient in recipe_data["extendedIngredients"]
    ]
    instruction_steps = [
        step["step"] for step in recipe_data["analyzedInstructions"][0]["steps"]
    ]

    # Check if the recipe already exists in "recipes" database
    db_recipe = Recipe.query.filter_by(title=recipe_title).first()

    if not db_recipe:
        # Create a new Recipe instance
        new_recipe = Recipe(title=recipe_title, image=recipe_image)
        db.session.add(new_recipe)
        db.session.commit()

        # Create Ingredient instances and link them to the Recipe instance
        for ingredient_name in ingredient_names:
            new_ingredient = Ingredient(name=ingredient_name, recipe_id=new_recipe.id)
            db.session.add(new_ingredient)
            db.session.commit()

        # Create Instruction instances and link them to the Recipe instance
        for step in instruction_steps:
            new_instruction = Instruction(step=step, recipe_id=new_recipe.id)
            db.session.add(new_instruction)
            db.session.commit()

        # Get the user's ID from the session
    user_id = session.get("user_id")

    # Update User's Saved Recipes
    if user_id:
        user = User.query.get(user_id)
        if user:
            db_recipe = Recipe.query.filter_by(title=recipe_title).first()
            # Check if the recipe already exists in "saved_recipes" database
            db_saved_recipe = SavedRecipe.query.filter_by(
                user_id=user_id, recipe_id=db_recipe.id
            ).first()
            if not db_saved_recipe:
                saved_recipe = SavedRecipe(recipe_id=db_recipe.id, user_id=user_id)
                # Swap recipe and user
                db.session.add(saved_recipe)
                db.session.commit()
                flash("Recipe saved successfully!", "success")
            else:
                flash("Recipe is already saved!", "info")

        else:
            flash("User not found!", "error")
    else:
        flash("User not authenticated!", "error")

    return redirect(f"/profile/{session['user_id']}")


@app.route("/recipe/<int:recipe_id>/unsave")
def unsave_recipe(recipe_id):
    # Remove the saved recipe from the user's profile
    user_id = session.get("user_id")
    if not user_id:
        flash("Access Unauthoried", "Danger")
        return redirect("/login")

    saved_recipes = SavedRecipe.query.filter_by(
        recipe_id=recipe_id, user_id=user_id
    ).all()
    for saved_recipe in saved_recipes:
        db.session.delete(saved_recipe)
        db.session.commit()
    flash("Recipe delated succesfully", "success")
    return redirect(f"/profile/{user_id}")


@app.route("/recipe/<int:recipe_id>/comment", methods=["POST"])
def post_comment(recipe_id):
    # Handle user comment submission and add to the database
    # Check if the user is logged in
    if not session["user_id"]:
        flash("You must be logged in to post a comment", "danger")
        return redirect("/login")

    user_id = session.get("user_id")

    # Get the form data
    text = request.form.get("text")
    parent_id = request.form.get("parent_id")

    if text:
        # Check if this is a reply to an existing comment
        if parent_id is not None:
            parent_comment = Comment.query.get(parent_id)
            if parent_comment:
                comment = Comment(
                    text=text,
                    user_id=session["user_id"],
                    recipe_id=recipe_id,
                    parent_id=parent_comment.id,
                    timestamp=datetime.utcnow(),
                )
                db.session.add(comment)
                db.session.commit()
                flash("Reply posted successfully!", "success")
            else:
                flash("Parent comment not found", "danger")
        else:
            # Handle regular comments
            comment = Comment(
                text=text,
                user_id=session["user_id"],
                recipe_id=recipe_id,
                timestamp=datetime.utcnow(),
            )
            db.session.add(comment)
            db.session.commit()
            flash("Comment posted successfully!", "success")
    else:
        flash("Comment cannot be empty", "danger")

    return redirect(f"/profile/{user_id}")


@app.route("/create_recipe", methods=["GET", "POST"])
def create_recipe():
    # Check if the user is logged in (You can adjust this part based on your authentication logic)
    user_id = session.get("user_id")
    if user_id is None:
        flash("You must be logged in to create a recipe", "danger")
        return redirect("/login")  # Redirect to the login page or an appropriate page

    # Create instances of the forms
    recipe_form = RecipeForm()
    ingredients_form = IngredientsForm(prefix="ingredients")
    instructions_form = InstructionsForm(prefix="instructions")

    if request.method == "POST":
        # Check if the submitted form is the recipe form
        if recipe_form.validate_on_submit():
            # Create a new recipe
            new_recipe = Recipe(
                title=recipe_form.title.data,
                user_generated=True,
                user_id=user_id,
                image=recipe_form.image.data,
                status="pending",
            )

            db.session.add(new_recipe)
            db.session.commit()

        # Check if the submitted form is the ingredients form
        if ingredients_form.validate_on_submit():
            # Loop through the submitted ingredients and add them to the recipe
            for ingredient_field in ingredients_form:
                if ingredient_field.data:
                    new_ingredient = Ingredient(
                        name=ingredient_field.data,
                        recipe=new_recipe,
                    )
                    db.session.add(new_ingredient)

        # Check if the submitted form is the instructions form
        if instructions_form.validate_on_submit():
            # Loop through the submitted instructions and add them to the recipe
            for instruction_field in instructions_form:
                if instruction_field.data:
                    new_instruction = Instruction(
                        step=instruction_field.data,
                        recipe=new_recipe,
                    )
                    db.session.add(new_instruction)

        # Commit all changes to the database
        db.session.commit()

        return redirect(f"/profile/{user_id}")  # Redirect to the user's profile page

    return render_template(
        "/created_recipes/create_recipe.html",
        recipe_form=recipe_form,
        ingredients_form=ingredients_form,
        instructions_form=instructions_form,
    )
