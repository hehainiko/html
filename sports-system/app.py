from flask import Flask, render_template, request, redirect, url_for, flash, session
app = Flask(__name__)
app.secret_key = 'sports_meet_secret_key_2024'

# 模拟登录
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        session['username'] = request.form.get('username')
        session['role'] = '管理员'
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 首页
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/team_register')
def team_register():
    return render_template('team_register.html')

@app.route('/event_register')
def event_register():
    return render_template('event_register.html')

@app.route('/score_input')
def score_input():
    return render_template('score_input.html')

@app.route('/query')
def query():
    return render_template('query.html')

@app.route('/members')
def members():
    return render_template('members.html')

@app.route('/team/<int:team_id>/members')
def team_members(team_id):
    return render_template('team_members.html')

# 让 Vercel 能运行
if __name__ == '__main__':
    app.run(debug=True)
