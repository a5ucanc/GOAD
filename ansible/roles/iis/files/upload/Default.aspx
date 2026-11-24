<%@ Page Language="C#" %>
<%-- Unrestricted upload (scenario iis-upload): any file, any extension, saved to upload/ and served
     from there, so an .aspx webshell runs as the application pool identity. Inline code: no bin folder. --%>
<script runat="server">
    protected void UploadFile(object sender, EventArgs e)
    {
        if (FileUpload1.HasFile)
        {
            string name = System.IO.Path.GetFileName(FileUpload1.FileName);
            FileUpload1.SaveAs(Server.MapPath("~/upload/") + name);
            Label1.Text = "File uploaded to upload/" + name;
        }
    }
</script>

<!DOCTYPE html>

<html xmlns="http://www.w3.org/1999/xhtml">
<head runat="server">
    <title></title>
</head>
<body>
    File uploader to the upload/ folder
    <form id="form1" runat="server">
        <div>
            <asp:FileUpload ID="FileUpload1" runat="server" /><br/>
            <asp:Button ID="Button1" runat="server" Text="Upload File" OnClick="UploadFile" /><br/>
            <asp:Label ID="Label1" runat="server" Text=""></asp:Label>
        </div>
    </form>
</body>
</html>
