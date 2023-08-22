# qq图文机器人

#### 介绍
用于qq的图文机器人

#### 软件架构
软件架构说明


#### 安装教程

1.打开config.yml,填入账号密码  
![输入图片说明](%E5%9B%BE%E7%89%871.png)  
2.打开chatgpt/config.cfg,修改qq信息  
![输入图片说明](%E5%9B%BE%E7%89%872.png)  
同样需要在这个配置文件中配置酒馆模式claude（推荐），claude或者gpt(至少配置一个)。  
**酒馆模式claude** ：修改slack_token，slack_cookie，slack_team_id，slack_channel，slack_claude_user,将qq号(大号或者群号)添加进sillyClaudeIdList将触发酒馆模式  
1.先解压插件“获取slack参数”，拖入谷歌浏览器扩展安装界面  
    ![输入图片说明](%E5%9B%BE3.png)    
    2.登录安装好claude的slack(未安装的去搜教程)，在任一频道@claude，然后打开插件获取上面4个参数  
    ![输入图片说明](%E5%9B%BE4.png)  
    3.点击claude应用，获取最后一个参数claude_user  
    ![输入图片说明](%E5%9B%BE%E4%BA%94.png)  

普通模式claude（基本弃用）:
```
    1.修改channel_id，格式为’channel_id:应用id’，  
    2.修改access_token（从https://chatgpt-proxy.lss233.com/claude-in-slack/login获取）  
    3.把2中添加的应用添加到channel_id对应的频道中  
```

gpt:配置api_key和proxy（chatgpt需要魔法）

**新增claude2酒馆模式：**
```
    1.卸载你的谷歌浏览器，安装项目内的谷歌浏览器94版，并设置禁止更新（右键打开文件位置，点击上上层的Google，修改update文件夹(没有就新建)安全权限为拒绝）：  
    2.打开chatgpt/config.cfg,将qq号(大号或者群号)添加进sillyClaudeIdList.启动后回复.切换账号即可   
    3.注意:.切换账号和claude2聊天需要魔法
```



画图stable diffusion：配置api_url  

3.修改预设，打开/presets/catgirl.txt,其中system为背景，role_desc为角色图片描述（删掉这行则不画图）  

4.启动ChatGPT.cmd和启动cqhttp1.1/go-cqhttp.bat   
注意：白嫖的别人共享签名服务器，挂了得重新找签名服务器改上去（cqhttp1.1/config.yml中的sign-server，来源https://github.com/Mrs4s/go-cqhttp/issues/2242）  

5.更多功能启动后对qq回复.help

#### 使用说明
1.启动后使用manager_qq发送.help查看常用命令


#### 参与贡献

1.  Fork 本仓库
2.  新建 Feat_xxx 分支
3.  提交代码
4.  新建 Pull Request

#### 说明
本项目基于聊天机器人https://github.com/lss233/chatgpt-mirai-qq-bot进行二次开发，主要特点为图文实时回复，酒馆模式（支持删除对话，重新回复）
第一次写python，基本改得一团糟，建议强迫症别看代码

