package se.gozem.myfirstapp;

import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.os.Bundle;
import android.support.design.widget.FloatingActionButton;
import android.support.design.widget.Snackbar;
import android.support.v7.app.AppCompatActivity;
import android.support.v7.widget.Toolbar;
import android.view.LayoutInflater;
import android.view.View;
import android.view.Menu;
import android.view.MenuItem;

import android.os.Build;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.NumberPicker;
import android.widget.TextView;
import android.util.Log;

import org.java_websocket.WebSocket;
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.drafts.Draft_17;
import org.java_websocket.handshake.ServerHandshake;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.net.URI;
import java.net.URISyntaxException;
import java.text.DateFormat;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Objects;
import java.util.TimeZone;

import android.content.Intent;

public class MyActivity extends AppCompatActivity {
    public final static String EXTRA_MESSAGE = "com.mycompany.myfirstapp.MESSAGE";

    private WebSocketClient mWebSocketClient;

    private TextView statusTextView;
    private TextView rainTextView;
    private TextView temp1TextView;
    private TextView temp2TextView;
    private TextView[] shuttersStateTextView;
    private TextView[] shuttersBusyTextView;
    private TextView[] shuttersHeadingTextView;
    private NumberPicker locktime;

    private ColorStateList defaultTextColor;

    private SharedPreferences sharedPref;

    private int mCurrentMinLocktime = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_my);

        /*
        Toolbar toolbar = (Toolbar) findViewById(R.id.toolbar);
        setSupportActionBar(toolbar);
        */

        statusTextView = (TextView)findViewById(R.id.status);
        defaultTextColor = statusTextView.getTextColors();

        rainTextView = (TextView)findViewById(R.id.rain);
        rainTextView.setTextColor(defaultTextColor);

        temp1TextView = (TextView)findViewById(R.id.temp1);
        temp1TextView.setTextColor(defaultTextColor);

        temp2TextView = (TextView)findViewById(R.id.temp2);
        temp2TextView.setTextColor(defaultTextColor);

        shuttersStateTextView = new TextView[6];
        shuttersStateTextView[0] = (TextView)findViewById(R.id.shutter1_state);
        shuttersStateTextView[1] = (TextView)findViewById(R.id.shutter2_state);
        shuttersStateTextView[2] = (TextView)findViewById(R.id.shutter3_state);
        shuttersStateTextView[3] = (TextView)findViewById(R.id.shutter4_state);
        shuttersStateTextView[4] = (TextView)findViewById(R.id.shutter5_state);
        shuttersStateTextView[5] = (TextView)findViewById(R.id.shutter6_state);

        shuttersBusyTextView = new TextView[6];
        shuttersBusyTextView[0] = (TextView)findViewById(R.id.shutter1_busy);
        shuttersBusyTextView[1] = (TextView)findViewById(R.id.shutter2_busy);
        shuttersBusyTextView[2] = (TextView)findViewById(R.id.shutter3_busy);
        shuttersBusyTextView[3] = (TextView)findViewById(R.id.shutter4_busy);
        shuttersBusyTextView[4] = (TextView)findViewById(R.id.shutter5_busy);
        shuttersBusyTextView[5] = (TextView)findViewById(R.id.shutter6_busy);

        shuttersHeadingTextView = new TextView[6];
        shuttersHeadingTextView[0] = (TextView)findViewById(R.id.shutter1_reason);
        shuttersHeadingTextView[1] = (TextView)findViewById(R.id.shutter2_reason);
        shuttersHeadingTextView[2] = (TextView)findViewById(R.id.shutter3_reason);
        shuttersHeadingTextView[3] = (TextView)findViewById(R.id.shutter4_reason);
        shuttersHeadingTextView[4] = (TextView)findViewById(R.id.shutter5_reason);
        shuttersHeadingTextView[5] = (TextView)findViewById(R.id.shutter6_reason);

        sharedPref = getSharedPreferences("se.gozem.myfirstapp.PREFERENCE_FILE_KEY", MODE_PRIVATE);

        TextView locationTextView = (TextView)findViewById(R.id.location);
        locationTextView.setText(sharedPref.getString("LOCATION", ""));

        connectWebSocket();
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        // Inflate the menu; this adds items to the action bar if it is present.
        getMenuInflater().inflate(R.menu.menu_my, menu);
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        // Handle action bar item clicks here. The action bar will
        // automatically handle clicks on the Home/Up button, so long
        // as you specify a parent activity in AndroidManifest.xml.
        int id = item.getItemId();

        //noinspection SimplifiableIfStatement
        if (id == R.id.action_settings) {
            return true;
        }

        return super.onOptionsItemSelected(item);
    }

    protected void showLocktimeDialog() {
        LayoutInflater layoutInflater = LayoutInflater.from(MyActivity.this);
        View locktimeView = layoutInflater.inflate(R.layout.dialog_locktime, null);
        AlertDialog.Builder builder = new AlertDialog.Builder(MyActivity.this);
        builder.setView(locktimeView);

        final NumberPicker locktimePicker = (NumberPicker) locktimeView.findViewById(R.id.locktimePicker);
        locktimePicker.setMinValue(0);
        locktimePicker.setMaxValue(5 * 60);
        locktimePicker.setWrapSelectorWheel(false);
        locktimePicker.setValue(mCurrentMinLocktime);
        locktimePicker.setClickable(true);

        final Button add15minButton = (Button) locktimeView.findViewById(R.id.locktimeAdd15MinButton);
        add15minButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                locktimePicker.setValue(locktimePicker.getValue() + 15);
            }
        });

        // setup a dialog window
        builder.setMessage("Select lock time")
                .setPositiveButton("OK", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface dialog, int id) {
                        mCurrentMinLocktime = locktimePicker.getValue();
                        Log.i("LockTime", "Locktime selected: " + locktimePicker.getValue());

                        if (mCurrentMinLocktime == 0) {
                            lockShutter("ALL", 0);
                        } else {
                            lockShutter("ALL", (System.currentTimeMillis() / 1000) + (mCurrentMinLocktime * 60)); //Convert to seconds
                        }
                    }
                })
                .setNegativeButton("Cancel", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface dialog, int id) {
                        dialog.cancel();
                    }
                });

        // create an alert dialog
        AlertDialog alert = builder.create();
        alert.show();
    }

    public void openLocktimeDialog(View view) {
        showLocktimeDialog();
    }


    private void connectWebSocket() {
        final String location = sharedPref.getString("LOCATION", "");
        Log.d("WebSocket", "Connecting to: " + location);

        URI uri;
        try {
            uri = new URI("ws://" + location + "/ws");
        } catch (URISyntaxException e) {
            e.printStackTrace();
            return;
        }

        mWebSocketClient = new WebSocketClient(uri) {
            private boolean closed = false;
            private String errorStr = "";

            private void setStatus(String status, int color) {
                final String myStatus = status;
                final int myColor = color;

                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        statusTextView.setText(myStatus);
                        statusTextView.setTextColor(myColor);
                    }
                });
            }

            private void clearStatus() {
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        rainTextView.setText("Unknown");
                        rainTextView.setTextColor(defaultTextColor);
                        temp1TextView.setText("Unknown");
                        temp1TextView.setTextColor(defaultTextColor);
                        temp2TextView.setText("Unknown");
                        temp2TextView.setTextColor(defaultTextColor);
                        for (int i = 0; i < 6; i++) {
                            shuttersStateTextView[i].setText("Unknown");
                            shuttersBusyTextView[i].setVisibility(View.INVISIBLE);
                            shuttersHeadingTextView[i].setText("");
                        }
                    }
                });

            }

            private void disconnect() {
                if (!closed) {
                    clearStatus();
                    setStatus("Disconnected! " + errorStr, Color.RED);
                    closed = true;
                }
            }

            @Override
            public void onOpen(ServerHandshake serverHandshake) {
                errorStr = ""; //Clear errors

                Log.i("Websocket", "Opened");

                setStatus("Connected to " + location, Color.GREEN);
            }

            @Override
            public void onMessage(String s) {
                final String message = s;
                runOnUiThread(new Runnable() {
                    private String prettyPrintState(String state) {
                        switch (state) {
                            case "OPEN":
                                return "Open";

                            case "CLOSED":
                                return "Closed";

                            case "GOING_UP":
                                return "Opening...";

                            case "GOING_DOWN":
                                return "Closing...";

                            case "STOPPED":
                                return "Stopped";

                            default:
                                return state;
                        }
                    }

                    @Override
                    public void run() {
                        Log.d("Websocket", "Got msg: " + message);
                        //TextView textView = (TextView)findViewById(R.id.messages);
                        //textView.setText(textView.getText() + "\n" + message);


                        try {
                            JSONObject jsonReader = new JSONObject(message);

                            try {
                                boolean rain = jsonReader.getBoolean("Rain");
                                if (rain) {
                                    rainTextView.setText("It is raining!");
                                    rainTextView.setTextColor(Color.RED);
                                } else {
                                    rainTextView.setText("No rain");
                                    rainTextView.setTextColor(defaultTextColor);
                                }

                            } catch (JSONException e) {
                                Log.e("JSON parser", "Error parsing JSON rain: " + e.toString());
                            }

                            try {
                                double temp1 = jsonReader.getDouble("TempSensor1");
                                temp1TextView.setText(temp1 + "°C");
                            } catch (JSONException e) {
                                temp1TextView.setText("Unknown");
                            }

                            try {
                                double temp2 = jsonReader.getDouble("TempSensor2");
                                temp2TextView.setText(temp2 + "°C");
                            } catch (JSONException e) {
                                temp2TextView.setText("Unknown");
                            }

                            for (int s=1; s<=6; s++) {
                                try {
                                    JSONObject shutterJSONObj = jsonReader.getJSONObject("Shutter" + s);

                                    String state = shutterJSONObj.getString("state");
                                    shuttersStateTextView[s-1].setText(prettyPrintState(state));

                                    boolean busy = shutterJSONObj.getBoolean("busy");
                                    shuttersBusyTextView[s-1].setVisibility(busy ? View.VISIBLE : View.INVISIBLE);

                                    /*
                                    String heading = shutterJSONObj.getString("heading");
                                    if (heading.equals(state)) {
                                        shuttersHeadingTextView[s-1].setText("");
                                    } else {
                                        shuttersHeadingTextView[s-1].setText(prettyPrintState(heading));
                                    }
                                    */

                                    long lockedTimeStamp = shutterJSONObj.getInt("locked");
                                    if (lockedTimeStamp > 0) {
                                        Date date = new Date(lockedTimeStamp * 1000);

                                        DateFormat df = new SimpleDateFormat("HH:mm");
                                        df.setTimeZone(TimeZone.getDefault());
                                        String locked = df.format(date);
                                        Log.i("Locked", locked);
                                        shuttersHeadingTextView[s-1].setText(locked);
                                    } else {
                                        shuttersHeadingTextView[s-1].setText("");
                                    }



                                } catch (JSONException e) {
                                    Log.e("JSON parser", "Error parsing JSON shutter" + s + ": " + e.toString());
                                }
                            }
                        } catch (JSONException e) {
                            Log.e("JSON parser", "Error parsing json: " + e.toString());
                        }

                    }
                });
            }

            @Override
            public void onClose(int i, String s, boolean b) {
                Log.i("Websocket", "Closed: " + s + " errorStr: " + errorStr);
                disconnect();
            }

            @Override
            public void onError(Exception e) {
                Log.e("Websocket", "Error: " + e.getMessage());
                errorStr = e.getMessage();

                if (!closed)
                    setStatus("Websocket error: " + e.getMessage(), Color.RED);
            }
        };

        TextView statusTextView = (TextView)findViewById(R.id.status);
        statusTextView.setText("Connecting...");
        statusTextView.setTextColor(Color.RED);
        mWebSocketClient.connect();
    }


    public void buttonConnect(View view) {
        mWebSocketClient.close();

        TextView textView = (TextView)findViewById(R.id.location);
        String loc = textView.getText().toString();
        Log.d("WebSocket", "buttonConnect: " + loc);

        SharedPreferences.Editor editor = sharedPref.edit();
        editor.putString("LOCATION", loc);
        editor.commit();

        connectWebSocket();
    }


    /*
    public void sendMessage(View view) {
        Intent intent = new Intent(this, DisplayMessageActivity.class);
        EditText editText = (EditText)findViewById(R.id.message);
        String message = editText.getText().toString();


        if (mWebSocketClient != null) {
            mWebSocketClient.send(message);
            Log.i("Websocket", "Sending!");
        } else {
            Log.e("Websocket", "Websocket is NULL");
        }

        intent.putExtra(EXTRA_MESSAGE, message);
        startActivity(intent);

        editText.setText("");
    }
    */


    private void lockShutter(String shutter, long timestamp) {
        JSONObject json = new JSONObject();
        try {
            json.put("what", "shutter");
            json.put("shutter", shutter);
            json.put("cmd", "LOCK");
            json.put("value", timestamp);
        } catch (JSONException e) {
            e.printStackTrace();
        }

        sendToServer(json.toString());
    }

    private void commandShutter(String shutter, String cmd) {
        JSONObject json = new JSONObject();
        try {
            json.put("what", "shutter");
            json.put("shutter", shutter);
            json.put("cmd", cmd);
        } catch (JSONException e) {
            e.printStackTrace();
        }

        sendToServer(json.toString());
    }


    private void sendToServer(String msg) {
        if (mWebSocketClient.getReadyState() == WebSocket.READYSTATE.OPEN)
            mWebSocketClient.send(msg);
    }

    public void sendAnyUp(View view) {
        commandShutter("ANY", "UP");
    }

    public void sendAnyDown(View view) {
        commandShutter("ANY", "DOWN");
    }
    
    public void sendAllUp(View view) {
        commandShutter("ALL", "UP");
    }

    public void sendAllDown(View view) {
        commandShutter("ALL", "DOWN");
    }

    public void sendAllStop(View view) {
        commandShutter("ALL", "STOP");
    }

    public void sendLockPlus15(View view) {
        lockShutter("ALL", (System.currentTimeMillis() / 1000) + 15 * 60); //Convert to seconds
    }

    public void sendLockMinus15(View view) {

    }
}
