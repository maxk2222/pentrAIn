# Customer portal — template & config evidence

## templates/customer/welcome.html

```html
<p>Welcome {{ request.args.name }}</p>
```

## routes.py (as shipped)

```python
@app.route("/welcome")
def welcome():
    return render_template("customer/welcome.html")

@app.route("/preview")
def preview():
    tpl = request.args.get("tpl", "welcome.html")
    return render_template("customer/" + tpl)
```

## App config

```python
app.config["TEMPLATES_AUTO_RELOAD"] = True
# sandbox: default Jinja2 environment
```

## Access log extract

```
GET /preview?tpl=welcome.html                      -> 200
GET /preview?tpl=../../etc/passwd                   -> 200
GET /welcome?name={{7*7}}                           -> 200  "Welcome 49"
```

## Service doc

The preview endpoint renders stored customer templates for QA review.
